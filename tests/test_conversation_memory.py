from unittest.mock import MagicMock, patch

import memory.conversation_memory as cm
from voice import document_state


def setup_function(_):
    # Defensive against execution order relative to
    # tests/test_creative_context_isolation.py -- recall()/recall_facts()
    # now short-circuit while a creative project is active, so every
    # test in this file needs a clean (no active project) slate
    # regardless of what ran immediately before it.
    document_state.clear_scope()


def teardown_function(_):
    document_state.clear_scope()



def test_remember_turn_truncates_long_replies(monkeypatch, fake_collection, fake_embedder):
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(cm, "_get_embedder", lambda: fake_embedder)
    cm.remember_turn("what did we decide", "x" * 1000)
    stored_doc = fake_collection.add.call_args.kwargs["documents"][0]
    assert len(stored_doc) < 700


def test_remember_turn_is_a_noop_for_empty_input(monkeypatch, fake_collection, fake_embedder):
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(cm, "_get_embedder", lambda: fake_embedder)
    cm.remember_turn("", "something")
    cm.remember_turn("something", "")
    assert fake_collection.add.call_count == 0


def test_recall_short_circuits_on_empty_collection(monkeypatch):
    empty = MagicMock()
    empty.count.return_value = 0
    monkeypatch.setattr(cm, "_get_collection", lambda: empty)
    assert cm.recall("anything") == []
    assert not empty.query.called


def test_recall_never_raises_on_internal_failure(monkeypatch):
    broken = MagicMock()
    broken.count.side_effect = Exception("db corrupted")
    monkeypatch.setattr(cm, "_get_collection", lambda: broken)
    assert cm.recall("anything") == []


def test_recall_uses_a_precomputed_embedding_when_given(monkeypatch, fake_collection):
    """recall() shouldn't call the embedder at all when a query_embedding
    is already supplied -- catching this via a raised exception wouldn't
    work here since recall() swallows all exceptions internally, so this
    tracks the call directly instead."""
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    fake_collection.count.return_value = 1
    fake_collection.query.return_value = {"documents": [["a past turn"]]}

    embedder_calls = []
    monkeypatch.setattr(cm, "_get_embedder", lambda: embedder_calls.append(True))

    result = cm.recall("anything", query_embedding=[0.9, 0.9])

    assert result == ["a past turn"]
    assert embedder_calls == [], "should not re-encode when query_embedding is already given"
    assert fake_collection.query.call_args.kwargs["query_embeddings"] == [[0.9, 0.9]]


def test_remember_fact_stores_with_category(monkeypatch, fake_collection, fake_embedder):
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: fake_collection)
    monkeypatch.setattr(cm, "_get_embedder", lambda: fake_embedder)
    result = cm.remember_fact("person", "My manager is named Sarah")
    assert "Sarah" in result and "person" in result
    metadata = fake_collection.add.call_args.kwargs["metadatas"][0]
    assert metadata["category"] == "person"


def test_remember_fact_normalizes_category(monkeypatch, fake_collection, fake_embedder):
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: fake_collection)
    monkeypatch.setattr(cm, "_get_embedder", lambda: fake_embedder)
    cm.remember_fact("  PREFERENCE  ", "Prefers dark mode")
    metadata = fake_collection.add.call_args.kwargs["metadatas"][0]
    assert metadata["category"] == "preference"


def test_remember_fact_empty_fact_is_a_noop(monkeypatch, fake_collection, fake_embedder):
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: fake_collection)
    monkeypatch.setattr(cm, "_get_embedder", lambda: fake_embedder)
    cm.remember_fact("person", "   ")
    assert fake_collection.add.call_count == 0


def test_list_facts_returns_chronological_order(monkeypatch):
    collection = MagicMock()
    collection.count.return_value = 2
    collection.get.return_value = {
        "documents": ["[person] Sarah is my manager", "[preference] Prefers dark mode"],
        "metadatas": [
            {"timestamp": "2026-07-15T10:00:00", "category": "person"},
            {"timestamp": "2026-07-10T09:00:00", "category": "preference"},
        ],
    }
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: collection)
    facts = cm.list_facts()
    assert facts[0] == "[preference] Prefers dark mode"
    assert facts[1] == "[person] Sarah is my manager"


def test_list_facts_filters_by_category(monkeypatch):
    collection = MagicMock()
    collection.count.return_value = 1
    collection.get.return_value = {
        "documents": ["[person] Sarah is my manager"],
        "metadatas": [{"timestamp": "2026-07-15T10:00:00", "category": "person"}],
    }
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: collection)
    cm.list_facts(category="person")
    assert collection.get.call_args.kwargs["where"] == {"category": "person"}


def test_forget_all_clears_both_collections(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(cm.chromadb, "PersistentClient", lambda path: client)
    result = cm.forget_all()
    deleted = [c.args[0] for c in client.delete_collection.call_args_list]
    assert set(deleted) == {"jarvis_conversations", "jarvis_facts"}
    assert "cleared" in result.lower()


# --- relevance filtering ----------------------------------------------
# recall()/recall_facts() used to return their top-k nearest neighbors
# unconditionally -- even a barely-related match got returned just for
# being the closest thing available once nothing genuinely relevant
# existed, and that noise got treated as signal in the prompt.

def test_recall_drops_results_below_the_relevance_threshold(monkeypatch, fake_collection):
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    fake_collection.count.return_value = 2

    query_embedding = [1.0, 0.0]
    fake_collection.query.return_value = {
        "documents": [["closely related turn", "unrelated turn"]],
        # cosine(query, [1, 0]) == 1.0 (identical direction)
        # cosine(query, [0, 1]) == 0.0 (orthogonal -- irrelevant)
        "embeddings": [[[1.0, 0.0], [0.0, 1.0]]],
    }

    from config import CONFIG as real_config
    with patch.dict(real_config, {"memory_relevance_threshold": 0.5}):
        result = cm.recall("anything", query_embedding=query_embedding)

    assert result == ["closely related turn"]


def test_recall_keeps_everything_when_all_above_threshold(monkeypatch, fake_collection):
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    fake_collection.count.return_value = 2

    query_embedding = [1.0, 0.0]
    fake_collection.query.return_value = {
        "documents": [["turn one", "turn two"]],
        "embeddings": [[[1.0, 0.0], [0.9, 0.1]]],
    }

    from config import CONFIG as real_config
    with patch.dict(real_config, {"memory_relevance_threshold": 0.5}):
        result = cm.recall("anything", query_embedding=query_embedding)

    assert result == ["turn one", "turn two"]


def test_recall_degrades_to_unfiltered_when_embeddings_are_missing(monkeypatch, fake_collection):
    """Older Chroma result shapes or a test double that doesn't return
    embeddings must not cause every candidate to be silently dropped --
    that would be a worse failure mode than the noise this feature
    exists to filter out."""
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    fake_collection.count.return_value = 1
    fake_collection.query.return_value = {"documents": [["a past turn"]]}

    result = cm.recall("anything", query_embedding=[1.0, 0.0])

    assert result == ["a past turn"]


def test_recall_facts_drops_results_below_the_relevance_threshold(monkeypatch, fake_collection):
    monkeypatch.setattr(cm, "_get_facts_collection", lambda: fake_collection)
    fake_collection.count.return_value = 2

    query_embedding = [1.0, 0.0]
    fake_collection.query.return_value = {
        "documents": [["[person] Sarah is my manager", "[preference] unrelated noise"]],
        "embeddings": [[[1.0, 0.0], [0.0, 1.0]]],
    }

    from config import CONFIG as real_config
    with patch.dict(real_config, {"memory_relevance_threshold": 0.5}):
        result = cm.recall_facts("who is my manager", query_embedding=query_embedding)

    assert result == ["[person] Sarah is my manager"]


def test_recall_requests_more_candidates_than_k_to_filter_from(monkeypatch, fake_collection):
    """Filtering by relevance after the nearest-neighbor query means k
    itself can't be the fetch size -- otherwise dropping even one
    below-threshold match leaves fewer than k results when better
    matches existed further down the ranking."""
    monkeypatch.setattr(cm, "_get_collection", lambda: fake_collection)
    fake_collection.count.return_value = 100
    fake_collection.query.return_value = {"documents": [[]], "embeddings": [[]]}

    cm.recall("anything", k=3, query_embedding=[1.0, 0.0])

    requested = fake_collection.query.call_args.kwargs["n_results"]
    assert requested > 3
