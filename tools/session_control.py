"""Tools that control Jarvis's session state and interaction mode."""

from voice import session_state


def mute_jarvis() -> str:
    session_state.mute()
    return "Jarvis is now muted. Spoken output is disabled until unmuted."


def unmute_jarvis() -> str:
    session_state.unmute()
    return "Jarvis is now unmuted."


def end_session() -> str:
    session_state.request_end()
    return "Session ending."


def enter_companion_mode() -> str:
    session_state.enter_companion_mode()
    return "Companion mode enabled."


def exit_companion_mode() -> str:
    session_state.exit_companion_mode()
    return "Back to normal mode."


def enter_creative_mode() -> str:
    session_state.enter_creative_mode()
    return "Creative writing mode enabled."


def exit_creative_mode() -> str:
    session_state.exit_creative_mode()
    return "Back to normal mode."


def enter_coding_mode() -> str:
    session_state.enter_coding_mode()
    return "Coding mode enabled."


def exit_coding_mode() -> str:
    session_state.exit_coding_mode()
    return "Back to normal mode."


SESSION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "mute_jarvis",
            "description": "Mute spoken Jarvis output.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unmute_jarvis",
            "description": "Unmute spoken Jarvis output.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_session",
            "description": "End the current Jarvis session.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enter_companion_mode",
            "description": "Switch Jarvis into open-ended companion conversation.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_companion_mode",
            "description": "Return Jarvis from companion mode to normal task mode.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enter_creative_mode",
            "description": "Switch Jarvis into creative writing/document-collaboration mode.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_creative_mode",
            "description": "Return Jarvis from creative mode to normal task mode.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enter_coding_mode",
            "description": "Switch Jarvis into coding mode (git, file, and dev tools).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_coding_mode",
            "description": "Return Jarvis from coding mode to normal task mode.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

SESSION_TOOL_FUNCTIONS = {
    "mute_jarvis": mute_jarvis,
    "unmute_jarvis": unmute_jarvis,
    "end_session": end_session,
    "enter_companion_mode": enter_companion_mode,
    "exit_companion_mode": exit_companion_mode,
    "enter_creative_mode": enter_creative_mode,
    "exit_creative_mode": exit_creative_mode,
    "enter_coding_mode": enter_coding_mode,
    "exit_coding_mode": exit_coding_mode,
}

SESSION_RISKY_TOOLS = {"end_session"}
