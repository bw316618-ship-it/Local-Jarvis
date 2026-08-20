"""
Shared mid-session state for Jarvis.

The active interaction mode is a named value rather than a collection of
independent boolean flags. This lets Jarvis add modes such as companion,
creative, coding, or journaling without duplicating the mode-switching
architecture.
"""

import threading

NORMAL = "normal"
COMPANION = "companion"
CREATIVE = "creative"
CODING = "coding"

VALID_MODES = {NORMAL, COMPANION, CREATIVE, CODING}

_mode_lock = threading.Lock()
_current_mode = NORMAL

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
