"""Tests for brain/tool_relevance.py.

Uses a small, fully deterministic fake embedder (fixed vectors keyed by
exact text) rather than the real SentenceTransformer -- ranking outcomes
need to be predictable for a unit test, not just plausible. Semantic
correctness of the real embedding model is out of scope here; what's
under test is the filtering mechanism itself: threshold gating, the
always-include set, top_k slicing, and the never-fail-the-turn fallback.
"""

from unittest.mock import MagicMock

import brain.tool_relevance as tool_relevance
from brain.tool_relevance import filter_tools_by_relevance


def setup_function():
    # The module-level embedding cache persists across tests by design
    # (that's the whole point -- embed each tool once per process). Tests
    # that care about exact call counts need a clean slate.
    tool_relevance._tool_embedding_cache.clear()


def _tool(name, description=""):
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": {}},
    }


class FakeEmbedder:
    """Maps exact text to a hand-picked vector. Cosine similarity between
    two vectors is 1.0 for identical vectors, 0.0 for orthogonal ones --
    used here to make "this tool is obviously the closest match" and
    "this tool is obviously unrelated" fully deterministic."""

    def __init__(self, vectors: dict, default=(0.0, 0.0, 1.0)):
        self.vectors = vectors
        self.default = default
        self.calls = []

    def encode(self, text):
        self.calls.append(text)
        vec = self.vectors.get(text, self.default)
        return MagicMock(tolist=lambda: list(vec))


# --- threshold gating ----------------------------------------------------

def test_returns_same_list_object_when_at_or_below_threshold():
    tools = [_tool(f"tool_{i}") for i in range(5)]
    result = filter_tools_by_relevance("anything", tools, threshold_count=30)
    assert result is tools


def test_filters_once_over_threshold():
    tools = [_tool(f"tool_{i}") for i in range(31)]
    embedder = FakeEmbedder({})
    result = filter_tools_by_relevance(
        "query", tools, embedder=embedder, threshold_count=30, top_k=5
    )
    assert len(result) < len(tools)


# --- always-include set ---------------------------------------------------

def test_session_control_tools_always_included_regardless_of_ranking():
    tools = [_tool(f"tool_{i}") for i in range(28)] + [
        _tool("mute_jarvis", "Mute spoken output."),
        _tool("end_session", "End the session."),
    ]
    # Every candidate maps to the same default vector, so ranking among
    # "rest" is arbitrary -- the point is mute_jarvis/end_session survive
    # regardless of where they'd have landed in that ranking.
    embedder = FakeEmbedder({})
    result = filter_tools_by_relevance(
        "totally unrelated query", tools, embedder=embedder, threshold_count=25, top_k=3
    )
    result_names = {t["function"]["name"] for t in result}
    assert "mute_jarvis" in result_names
    assert "end_session" in result_names


# --- relevance ranking -----------------------------------------------------

def test_semantically_closer_tool_is_ranked_above_unrelated_ones():
    filler = [_tool(f"filler_{i}", "unrelated filler tool") for i in range(29)]
    weather_tool = _tool("get_weather", "Get the current weather forecast")
    tools = filler + [weather_tool]

    embedder = FakeEmbedder({
        "what's the weather like today": (1.0, 0.0, 0.0),
        "get_weather: Get the current weather forecast": (1.0, 0.0, 0.0),
    }, default=(0.0, 1.0, 0.0))

    result = filter_tools_by_relevance(
        "what's the weather like today",
        tools,
        embedder=embedder,
        threshold_count=25,
        top_k=1,
    )
    result_names = {t["function"]["name"] for t in result}
    assert "get_weather" in result_names


def test_top_k_limits_the_non_always_included_portion():
    tools = [_tool(f"tool_{i}", f"description {i}") for i in range(40)]
    embedder = FakeEmbedder({})
    result = filter_tools_by_relevance(
        "query", tools, embedder=embedder, threshold_count=30, top_k=5
    )
    assert len(result) == 5  # none of these names are in the always-include set


# --- caching ---------------------------------------------------------------

def test_tool_embeddings_are_cached_across_calls():
    tools = [_tool(f"tool_{i}", "same description") for i in range(35)]
    embedder = FakeEmbedder({})

    filter_tools_by_relevance("first query", tools, embedder=embedder, threshold_count=30, top_k=10)
    calls_after_first = len(embedder.calls)
    filter_tools_by_relevance("second query", tools, embedder=embedder, threshold_count=30, top_k=10)
    calls_after_second = len(embedder.calls)

    # Second call should only add 1 new encode() call (the query itself) --
    # every tool's embedding should already be cached from the first call.
    assert calls_after_second - calls_after_first == 1


# --- fail-safe behavior ---------------------------------------------------

def test_never_raises_and_returns_full_list_when_embedder_explodes():
    tools = [_tool(f"tool_{i}") for i in range(35)]

    class BrokenEmbedder:
        def encode(self, text):
            raise RuntimeError("embedding backend unavailable")

    result = filter_tools_by_relevance(
        "query", tools, embedder=BrokenEmbedder(), threshold_count=30, top_k=5
    )
    assert result == tools


def test_never_raises_when_query_embedding_is_malformed():
    tools = [_tool(f"tool_{i}") for i in range(35)]
    embedder = FakeEmbedder({})
    # A malformed pre-computed query_embedding (not a real vector) should
    # be caught, not propagate out of chat().
    result = filter_tools_by_relevance(
        "query", tools, embedder=embedder, query_embedding="not-a-vector",
        threshold_count=30, top_k=5,
    )
    assert result == tools


def test_uses_real_shared_embedder_when_none_provided(monkeypatch):
    """Default path (no embedder passed) should reach memory.shared.get_embedder --
    confirms the wiring, without needing the real SentenceTransformer loaded."""
    import memory.shared as shared

    fake = FakeEmbedder({})
    monkeypatch.setattr(shared, "get_embedder", lambda: fake)

    tools = [_tool(f"tool_{i}") for i in range(35)]
    result = filter_tools_by_relevance("query", tools, threshold_count=30, top_k=5)
    assert len(result) == 5
    assert fake.calls  # the shared embedder was actually used
