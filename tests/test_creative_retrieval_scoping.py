"""Regression tests for the retrieval-scoping leak between creative
projects and ordinary NORMAL-mode conversations.

Before this fix, brain/llm.py's baseline "context" block (built on every
non-trivial, non-companion turn) called JarvisMemory.search() with no
project filter -- source_type=MANUAL only. That meant:

  - In NORMAL mode, anything ingested into a creative project could
    resurface as "reference information" in ordinary task conversations
    that have nothing to do with that project.
  - In CREATIVE mode, the baseline context pulled from every project plus
    ingest.py's general knowledge base instead of respecting the active
    document/project boundary CREATIVE_PROMPT tells the model is in
    effect -- undermining "retrieved source material is canon".
"""

from unittest.mock import MagicMock

import brain.llm as llm_module
from brain.llm import JarvisLLM
from brain.mode_config import CREATIVE, NORMAL
from voice import document_state, session_state


def setup_function():
    session_state.set_mode(NORMAL)
    document_state.clear_scope()


def teardown_function():
    session_state.set_mode(NORMAL)
    document_state.clear_scope()


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK-MODE-PROMPT"
    jarvis.companion_system_prompt = "COMPANION-MODE-PROMPT"
    jarvis.model = "qwen3:8b"
    jarvis.short_term = []
    return jarvis


def _stream(content, tool_calls=None):
    return iter([{"message": {"content": content, "tool_calls": tool_calls}}])


def _patch_common_chat_deps(monkeypatch, jarvis, streamed_reply="ok"):
    fake_client = MagicMock()
    fake_client.chat.side_effect = (
        lambda model, messages, tools=None, stream=False, **kwargs: _stream(streamed_reply, None)
    )
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "get_embedder", lambda: MagicMock(encode=lambda q: MagicMock(tolist=lambda: [0.0])))
    return fake_client


# --- unit-level: JarvisMemory.search propagates the project filter -------

def test_jarvis_memory_search_passes_project_filter_through(monkeypatch):
    from memory.retriever import JarvisMemory

    memory = JarvisMemory.__new__(JarvisMemory)
    captured = {}

    def fake_document_search(query, source_type, k, query_embedding=None, project=None, source=None):
        captured["source_type"] = source_type
        captured["project"] = project
        return {"documents": [], "metadatas": []}

    import memory.retriever as retriever_module
    monkeypatch.setattr(retriever_module.document_store, "search", fake_document_search)

    memory.search("anything", project="")

    assert captured["source_type"] == retriever_module.document_store.MANUAL
    assert captured["project"] == ""


# --- integration-level: NORMAL mode excludes project-tagged documents ----

def test_normal_mode_excludes_project_scoped_documents(monkeypatch):
    jarvis = make_jarvis()
    jarvis.memory = MagicMock()
    jarvis.memory.search.return_value = []
    _patch_common_chat_deps(monkeypatch, jarvis)

    session_state.set_mode(NORMAL)
    jarvis.chat("what's the weather forecast look like", on_step=lambda m: None)

    jarvis.memory.search.assert_called_once()
    _, kwargs = jarvis.memory.search.call_args
    assert kwargs.get("project") == "", (
        "NORMAL mode must filter to project='' (untagged) documents only, "
        "or creative-project content can leak into ordinary conversations"
    )


# --- integration-level: CREATIVE mode uses scoped retrieval, not the ----
# --- generic unscoped JarvisMemory.search -------------------------------

def test_creative_mode_uses_get_creative_context_not_generic_search(monkeypatch):
    jarvis = make_jarvis()
    jarvis.memory = MagicMock()
    _patch_common_chat_deps(monkeypatch, jarvis)

    captured_calls = []
    monkeypatch.setattr(
        llm_module,
        "get_creative_context",
        lambda query, k=8, query_embedding=None: captured_calls.append((query, k, query_embedding))
        or "[Story passage 1]\ncanon text",
    )

    session_state.set_mode(CREATIVE)
    document_state.set_active_document(r"C:\story.pdf")

    jarvis.chat("what happens to the crown", on_step=lambda m: None)

    assert len(captured_calls) == 1
    query, k, query_embedding = captured_calls[0]
    assert query == "what happens to the crown"
    assert k == 8
    jarvis.memory.search.assert_not_called()


def test_creative_mode_context_reflects_active_project_scope(monkeypatch):
    """get_creative_context (used for CREATIVE mode's automatic baseline
    context) must pass the active project through to document_store.search
    -- not just source_type=MANUAL -- so retrieval stays within that
    project's documents rather than every project plus the general
    knowledge base."""
    import memory.document_store as document_store

    captured = {}

    def fake_search(query, source_type, k=5, query_embedding=None, source=None, project=None):
        captured["source_type"] = source_type
        captured["source"] = source
        captured["project"] = project
        return {"documents": ["a passage from Project A"], "metadatas": []}

    monkeypatch.setattr(document_store, "search", fake_search)

    session_state.set_mode(CREATIVE)
    document_state.clear_active_document()
    document_state.set_active_project("Project A")

    from tools.creative_generation import get_creative_context
    result = get_creative_context("anything")

    assert captured["source_type"] == document_store.MANUAL
    assert captured["source"] is None
    assert captured["project"] == "Project A"
    assert "Project A" in result
