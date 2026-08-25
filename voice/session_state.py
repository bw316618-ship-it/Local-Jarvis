"""
Shared mid-session state for Jarvis.

The active interaction mode is a named value rather than a collection of
independent boolean flags. This lets Jarvis add modes such as companion,
creative, coding, or journaling without duplicating the mode-switching
architecture.

Brain tier (fast/heavy) is tracked separately from interaction mode
rather than folded into it. A user might want the heavier model while
in coding mode just as easily as in normal mode -- tying "heavy" to a
specific mode would mean either duplicating every mode into a "heavy"
variant or losing the choice when switching modes mid-session. Keeping
it a second independent flag avoids both.
"""

import threading

NORMAL = "normal"
COMPANION = "companion"
CREATIVE = "creative"
CODING = "coding"

VALID_MODES = {NORMAL, COMPANION, CREATIVE, CODING}

BRAIN_FAST = "fast"
BRAIN_HEAVY = "heavy"

_mode_lock = threading.Lock()
_current_mode = NORMAL

_brain_lock = threading.Lock()
_current_brain_tier = BRAIN_FAST

_mute_event = threading.Event()
_end_requested_event = threading.Event()


def mute() -> None:
    _mute_event.set()


def unmute() -> None:
    _mute_event.clear()


def is_muted() -> bool:
    return _mute_event.is_set()


def request_end() -> None:
    _end_requested_event.set()


def is_end_requested() -> bool:
    return _end_requested_event.is_set()


def clear_end_request() -> None:
    _end_requested_event.clear()


def current_mode() -> str:
    with _mode_lock:
        return _current_mode


def set_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown Jarvis mode '{mode}'. "
            f"Valid modes: {sorted(VALID_MODES)}"
        )

    global _current_mode

    with _mode_lock:
        _current_mode = mode
        return _current_mode


def is_companion_mode() -> bool:
    """Compatibility helper for existing callers."""
    return current_mode() == COMPANION


def enter_companion_mode() -> None:
    set_mode(COMPANION)


def exit_companion_mode() -> None:
    set_mode(NORMAL)


def toggle_companion_mode() -> bool:
    if is_companion_mode():
        exit_companion_mode()
    else:
        enter_companion_mode()

    return is_companion_mode()


def enter_creative_mode() -> None:
    set_mode(CREATIVE)


def exit_creative_mode() -> None:
    set_mode(NORMAL)


def enter_coding_mode() -> None:
    set_mode(CODING)


def exit_coding_mode() -> None:
    set_mode(NORMAL)


def current_brain_tier() -> str:
    with _brain_lock:
        return _current_brain_tier


def set_brain_tier(tier: str) -> str:
    if tier not in (BRAIN_FAST, BRAIN_HEAVY):
        raise ValueError(
            f"Unknown brain tier '{tier}'. Valid tiers: {sorted((BRAIN_FAST, BRAIN_HEAVY))}"
        )

    global _current_brain_tier

    with _brain_lock:
        _current_brain_tier = tier
        return _current_brain_tier


def is_heavy_brain() -> bool:
    return current_brain_tier() == BRAIN_HEAVY


def enter_heavy_brain() -> None:
    set_brain_tier(BRAIN_HEAVY)


def exit_heavy_brain() -> None:
    set_brain_tier(BRAIN_FAST)
