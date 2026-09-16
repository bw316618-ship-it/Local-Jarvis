"""Varied, in-persona lines for Jarvis's own mechanical moments.

tools/session_control.py used to return one fixed string per event
("Companion mode enabled.", "Confirmed.") -- correct, but static in a
way that made the character disappear exactly where it's most visible:
every mode switch, mute, and session end sounded like a form response
rather than the composed, dryly witty J.A.R.V.I.S. persona established
in brain/llm.py's system prompt. This module is that persona applied
to those small, frequent, otherwise-invisible moments.

pick(event) returns one line from POOLS[event] at random -- not the
first, and not cycling in a fixed order, so the same phrase doesn't
reliably follow the same action every time. Tests assert membership
(`pick(event) in POOLS[event]`) rather than mocking random.choice, so
the pools can grow or reword freely without touching test internals.
"""

import random

POOLS = {
    "mute": [
        "Muted. I'll keep listening, just quietly.",
        "Going quiet now.",
        "Muted -- say the word when you'd like me back.",
    ],
    "unmute": [
        "Unmuted.",
        "Back and audible.",
        "I'm listening again.",
    ],
    "end_session": [
        "Ending the session. Until next time.",
        "Signing off.",
        "Session closed. I'll be here when you need me.",
    ],
    "enter_companion": [
        "Companion mode. I'm listening -- no agenda.",
        "Switching to companion mode. Take your time.",
        "I'm here to talk, not to task-manage.",
    ],
    "exit_companion": [
        "Back to business.",
        "Companion mode off -- normal mode restored.",
        "Right, back to task mode.",
    ],
    "enter_creative": [
        "Creative mode engaged. Let's build something.",
        "Switching into creative mode -- what are we writing?",
        "Creative mode on. I'm ready when the story is.",
    ],
    "exit_creative": [
        "Leaving creative mode.",
        "Back to normal mode -- the story will keep.",
        "Creative mode off.",
    ],
    "enter_coding": [
        "Coding mode. Let's see what we're working with.",
        "Switching into coding mode -- lead the way.",
        "Coding mode engaged.",
    ],
    "exit_coding": [
        "Leaving coding mode.",
        "Back to normal mode.",
        "Coding mode off.",
    ],
    "enter_heavy_brain": [
        "Switching to the larger model -- this may take a moment longer.",
        "Bringing the heavier model online. Worth the wait.",
        "Heavy brain engaged -- thinking a little slower, a little harder.",
    ],
    "exit_heavy_brain": [
        "Back to the fast default model.",
        "Dropping back to the quicker model.",
        "Fast model restored.",
    ],
}


def pick(event: str) -> str:
    """Return one persona-appropriate line for `event`.

    Falls back to the event name itself (rather than raising) if an
    unknown event is passed -- a missing pool shouldn't be able to
    break the tool call that wanted a phrase from it.
    """
    pool = POOLS.get(event)
    if not pool:
        return event
    return random.choice(pool)
