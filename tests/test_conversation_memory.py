"""Long-term memory: turn storage/recall, structured fact storage/listing,
and forget_all clearing both stores."""

from unittest.mock import MagicMock

import memory.conversation_memory as cm


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
