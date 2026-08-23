"""
Fast deterministic router for Jarvis.

The router prevents trivial/system requests from reaching the LLM.

The important rule:

If Python can determine the user's intent safely and deterministically,
do not spend LLM inference time determining it again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Route:
    name: str
    requires_llm: bool = True
    reason: str = ""


_SIMPLE_RESPONSES = {
    "hi": "Hello.",
    "hello": "Hello.",
    "hey": "Hello.",
    "hiya": "Hello.",
    "good morning": "Good morning.",
    "good afternoon": "Good afternoon.",
    "good evening": "Good evening.",
    "thanks": "You're welcome.",
    "thank you": "You're welcome.",
    "thx": "You're welcome.",
    "ok": "Understood.",
    "okay": "Understood.",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def get_instant_response(text: str) -> Optional[str]:
    return _SIMPLE_RESPONSES.get(_normalise(text))


_FAST_PATTERNS = {
    "time": (
        r"^\s*(what('?s| is) the )?time\??\s*$",
        r"^\s*current time\??\s*$",
    ),
    "date": (
        r"^\s*(what('?s| is) )?(today'?s )?date\??\s*$",
        r"^\s*what day is it\??\s*$",
    ),
    "system": (
        r"^\s*(open|launch|start|close|quit)\s+",
        r"^\s*(turn|set)\s+(volume|brightness)\b",
        r"^\s*(mute|unmute)\b",
    ),
    "maps": (
        r"\bnearby\b",
        r"\bnear me\b",
        r"\bnearest\b",
        r"\bdirections?\b",
        r"\bnavigate\b",
        r"\broute\b",
        r"\bpin\b.*\b(cafe|cafes|restaurant|restaurants|hotel|hotels|"
        r"hospital|hospitals|shop|shops|store|stores|bank|banks)\b",
        r"\b(find|show|search)\b.*\b(nearby|near me)\b",
    ),
    "search": (
        r"^\s*(search|google|look up)\b",
    ),
}


def classify(text: str) -> Route:
    normalized = _normalise(text)

    if not normalized:
        return Route(name="empty", requires_llm=False, reason="empty input")

    if normalized in _SIMPLE_RESPONSES:
        return Route(
            name="instant_conversation",
            requires_llm=False,
            reason="deterministic response",
        )

    for route_name, patterns in _FAST_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                return Route(
                    name=route_name,
                    requires_llm=True,
                    reason=f"matched {route_name} route",
                )

    return Route(name="llm", requires_llm=True, reason="no deterministic route matched")


_MULTI_STEP_HINTS = (
    " and then ",
    " then ",
    " after that ",
    " once ",
    " first ",
    " next ",
    " finally ",
)


def looks_multi_step(text: str) -> bool:
    normalized = _normalise(text)

    if len(normalized) > 250:
        return True
    if any(hint in normalized for hint in _MULTI_STEP_HINTS):
        return True
    if normalized.count(" and ") >= 1 and len(normalized.split()) >= 7:
        return True
    if normalized.count(",") >= 2:
        return True

    return False
