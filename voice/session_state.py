"""
Shared mid-session state for Jarvis, reachable from stateless tool
functions.

Tools in tools/*.py are plain functions with no reference to the live
JarvisVoice instance or the running main.py loop -- there's no existing
side channel for a tool call to affect either. This module is that
channel, kept deliberately minimal:

  - A mute flag: tools/session_control.py's mute_jarvis/unmute_jarvis
    set it, voice/voice.py's speak()/speak_async() check it before
    producing audio. Muting silences spoken output without touching
    text replies or ending the session.

  - An end-session flag: tools/session_control.py's end_session() sets
    it. main.py's chat loop (and the /wake loop) check it right after
    each handle_message() call and exit cleanly if it's set -- the same
    effect as the user typing "exit", just triggered by the model
    instead. A flag is used here rather than raising an exception,
    since brain/llm.py's _run_tool_call() already wraps every tool call
    in a blanket try/except that would otherwise swallow it into a
    generic "Error running tool" string instead of actually ending
    anything.

Both flags are threading.Event objects so they're safe to read from
main.py's loop and write from a tool call that (via the HUD's daemon
path) may run on a different thread.
"""

import threading

_mute_event = threading.Event()
_end_requested_event = threading.Event()


def mute() -> None:
    """Silence Jarvis's spoken output until unmute() is called."""
    _mute_event.set()


def unmute() -> None:
    """Re-enable Jarvis's spoken output."""
    _mute_event.clear()


def is_muted() -> bool:
    return _mute_event.is_set()


def request_end() -> None:
    """Signal that the current session should end, equivalent to the user
    typing 'exit'. Checked by main.py's loop after each turn."""
    _end_requested_event.set()


def is_end_requested() -> bool:
    return _end_requested_event.is_set()


def clear_end_request() -> None:
    """Reset the end-session flag. Called by main.py once it's acted on
    the request, so a fresh run of the app doesn't start pre-ended."""
    _end_requested_event.clear()
