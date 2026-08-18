"""
Session control tools for Jarvis: muting spoken output and ending the
current session.

mute_jarvis/unmute_jarvis toggle voice/session_state.py's shared mute
flag, which voice/voice.py's speak()/speak_async() check before actually
producing audio -- so "mute" silences Jarvis's voice without killing the
whole assistant. Both are safe (non-destructive, instantly reversible).

end_session sets voice/session_state.py's end-request flag rather than
raising an exception -- see that module's docstring for why (the tool-
call wrapper in brain/llm.py would otherwise swallow an exception into a
generic error string instead of actually ending anything). main.py's
loop checks the flag after every turn and exits cleanly, the same way it
already handles the typed "exit"/"quit" commands.

end_session is registered as risky since, unlike mute/unmute, it's not
trivially reversible once the loop exits.
"""

from voice import session_state


def mute_jarvis() -> str:
    """Silence Jarvis's spoken output until unmuted."""
    session_state.mute()
    return "Muted -- Jarvis will stop speaking replies aloud until unmuted."


def unmute_jarvis() -> str:
    """Re-enable Jarvis's spoken output."""
    session_state.unmute()
    return "Unmuted -- Jarvis will speak replies aloud again."


def end_session() -> str:
    """End the current Jarvis session, equivalent to the user typing 'exit'."""
    session_state.request_end()
    return "Ending session -- goodbye."


SESSION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "mute_jarvis",
            "description": "Silence Jarvis's spoken voice output until unmuted. Does not affect text replies.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unmute_jarvis",
            "description": "Re-enable Jarvis's spoken voice output after it's been muted.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_session",
            "description": (
                "End the current Jarvis session, equivalent to the user typing "
                "'exit'. Only call this when the user clearly wants to disconnect "
                "or stop talking to Jarvis (e.g. 'that's all, goodbye', 'disconnect')."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

SESSION_TOOL_FUNCTIONS = {
    "mute_jarvis": mute_jarvis,
    "unmute_jarvis": unmute_jarvis,
    "end_session": end_session,
}

# Muting/unmuting are trivially reversible, local-state-only toggles.
# Ending the session is not trivially reversible once the loop exits.
SESSION_RISKY_TOOLS = {"end_session"}
