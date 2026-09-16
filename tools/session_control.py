"""Tools that control Jarvis's session state and interaction mode."""

from brain import persona_lines
from voice import session_state


def mute_jarvis() -> str:
    session_state.mute()
    return persona_lines.pick("mute")


def unmute_jarvis() -> str:
    session_state.unmute()
    return persona_lines.pick("unmute")


def end_session() -> str:
    session_state.request_end()
    return persona_lines.pick("end_session")


def enter_companion_mode() -> str:
    session_state.enter_companion_mode()
    return persona_lines.pick("enter_companion")


def exit_companion_mode() -> str:
    session_state.exit_companion_mode()
    return persona_lines.pick("exit_companion")


def enter_creative_mode() -> str:
    session_state.enter_creative_mode()
    return persona_lines.pick("enter_creative")


def exit_creative_mode() -> str:
    session_state.exit_creative_mode()
    return persona_lines.pick("exit_creative")


def enter_coding_mode() -> str:
    session_state.enter_coding_mode()
    return persona_lines.pick("enter_coding")


def exit_coding_mode() -> str:
    session_state.exit_coding_mode()
    return persona_lines.pick("exit_coding")


def enter_heavy_brain() -> str:
    session_state.enter_heavy_brain()
    return persona_lines.pick("enter_heavy_brain")


def exit_heavy_brain() -> str:
    session_state.exit_heavy_brain()
    return persona_lines.pick("exit_heavy_brain")


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
    {
        "type": "function",
        "function": {
            "name": "enter_heavy_brain",
            "description": (
                "Switch to the larger, slower model for this session -- use when the "
                "user explicitly asks for more careful reasoning, a harder problem, or "
                "says something like 'use your best model' or 'think harder about this'. "
                "Independent of interaction mode; stays on until exit_heavy_brain is called."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_heavy_brain",
            "description": "Switch back to the fast default model.",
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
    "enter_heavy_brain": enter_heavy_brain,
    "exit_heavy_brain": exit_heavy_brain,
}

SESSION_RISKY_TOOLS = {"end_session"}
