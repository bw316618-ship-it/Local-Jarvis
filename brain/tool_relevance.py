"""
Relevance-based tool filtering.

NORMAL mode's tool registry has grown to 65+ schemas as features accrued
over time (git, files, media, calendar, maps, desktop automation, and
more, all merged into tools/tools.py's one flat TOOL_SCHEMAS list).
Offering a local 4-8B model all 65 candidates on every single turn
measurably hurts tool-selection accuracy versus a shorter, targeted
list -- this is precisely the kind of degradation this project's own
history already flags as a real concern (the model default was switched
from llama3.1:8b to qwen3:8b specifically because of tool-calling
reliability). Growing the tool list without bound works directly against
that.

This module narrows what's *offered* to the model each turn to the
tools most relevant to that turn's message, reusing the same embedding
infrastructure already used for document/fact retrieval (a
SentenceTransformer via memory/shared.get_embedder) rather than adding a
second model or a new dependency. It does not change what's dispatchable
-- brain/llm.py's _run_tool_call still resolves against the full
per-mode function registry regardless of what was shown, so a ranking
mistake can only ever cause a tool to be temporarily unavailable that
turn, never make an unintended tool callable.

A fixed set of tools is always included regardless of relevance ranking:
session-control (mute/unmute/end_session/enter_*_mode/exit_*_mode).
Losing access to those specifically mid-conversation because they didn't
score high enough for an unrelated query would be a real usability
regression, not just a missed shortcut -- you need to be able to leave a
mode or end the session no matter what you're in the middle of saying.

Filtering only kicks in once a mode's tool count actually exceeds
CONFIG["tool_relevance_threshold"], so this is self-limiting: small
modes (COMPANION today at ~9, CREATIVE at ~20, CODING at ~23) pass
through unchanged, and only a mode that's actually grown large enough
for this to matter pays the (small, cached) extra cost.
"""

import math

_ALWAYS_INCLUDE_NAMES = frozenset({
    "mute_jarvis",
    "unmute_jarvis",
    "end_session",
    "enter_companion_mode",
    "exit_companion_mode",
    "enter_creative_mode",
    "exit_creative_mode",
    "enter_coding_mode",
    "exit_coding_mode",
})

# Tool name -> embedding vector. Tool schemas are static for the process
# lifetime, so each tool only ever needs embedding once, not on every
# chat turn -- re-embedding 65 short strings per turn would add real,
# pointless per-turn latency.
_tool_embedding_cache: dict = {}


def _tool_text(tool: dict) -> str:
    fn = tool["function"]
    return f"{fn['name']}: {fn.get('description', '')}".strip()


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_for_tool(tool: dict, embedder) -> list:
    name = tool["function"]["name"]
    cached = _tool_embedding_cache.get(name)
    if cached is not None:
        return cached
    vector = embedder.encode(_tool_text(tool)).tolist()
    _tool_embedding_cache[name] = vector
    return vector


def filter_tools_by_relevance(
    query: str,
    tools: list,
    embedder=None,
    query_embedding: list = None,
    top_k: int = 20,
    threshold_count: int = 30,
) -> list:
    """Return a relevance-narrowed subset of `tools` for `query`.

    Returns `tools` unchanged (same list object, not a copy) whenever
    len(tools) <= threshold_count -- filtering never runs for a mode
    small enough that it wouldn't help.

    Always includes every tool in _ALWAYS_INCLUDE_NAMES that's present in
    `tools`, regardless of ranking, then adds the top_k highest-scoring
    remaining tools by cosine similarity between the query and each
    tool's "name: description" text.

    Falls back to returning `tools` unchanged -- never a smaller, empty,
    or broken list -- if embedding fails for any reason (embedder
    unavailable, encode() raises, etc.). A filtering failure must never
    be able to block a chat turn outright; worst case, the model just
    sees the full list again, exactly as if this module didn't exist.
    """
    if len(tools) <= threshold_count:
        return tools

    always = [t for t in tools if t["function"]["name"] in _ALWAYS_INCLUDE_NAMES]
    rest = [t for t in tools if t["function"]["name"] not in _ALWAYS_INCLUDE_NAMES]

    try:
        if embedder is None:
            from memory.shared import get_embedder
            embedder = get_embedder()
        if query_embedding is None:
            query_embedding = embedder.encode(query).tolist()

        scored = [
            (t, _cosine(query_embedding, _embedding_for_tool(t, embedder)))
            for t in rest
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        ranked = [t for t, _score in scored[:top_k]]
    except Exception:
        return tools

    return always + ranked
