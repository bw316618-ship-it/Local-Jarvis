"""
Mouse and keyboard control for Jarvis, via PyAutoGUI.

The import is deferred into _get_pyautogui() rather than sitting at the
top of the file, so a machine without a display/GUI session (or without
pyautogui installed) doesn't crash the whole assistant on startup -- only
these specific tools fail, with a clear error.

mouse_click, keyboard_type, and keyboard_hotkey are registered as risky in
tools/tools.py: they drive whatever is actually on screen, so Jarvis
confirms before using them. screen_size is read-only info and isn't risky.
"""

from functools import wraps


def _get_pyautogui():
    try:
        import pyautogui
    except (ImportError, OSError) as e:
        raise RuntimeError(
            "Desktop control isn't available: pyautogui is not installed "
            "or couldn't access the display. Run: pip install -r requirements.txt"
        ) from e

    pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
    return pyautogui


def _catch_backend_unavailable(func):
    """Every function below calls _get_pyautogui() first, which raises a
    RuntimeError with an already-complete, self-explanatory message when
    the backend isn't available (not installed, no display) -- each one
    was catching that and returning str(e) unchanged. This decorator does
    that one shared step so each function only needs its own try/except
    around the actual action, for its own action-specific failure
    message. (tools/window_control.py has an identical copy of this for
    _get_gw() -- small and self-contained enough in each file that it
    isn't worth a new shared module for just the two of them; promote it
    if a third module needs the same pattern.)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            return str(e)
    return wrapper


@_catch_backend_unavailable
def mouse_click(x: int, y: int, button: str = "left") -> str:
    """Click the mouse at the given screen coordinates."""
    pyautogui = _get_pyautogui()
    try:
        pyautogui.click(x=x, y=y, button=button)
        return f"Clicked ({x}, {y}) with {button} button."
    except Exception as e:
        return f"Could not click at ({x}, {y}): {e}"


@_catch_backend_unavailable
def keyboard_type(text: str) -> str:
    """Type text at wherever the keyboard focus currently is."""
    pyautogui = _get_pyautogui()
    try:
        pyautogui.write(text, interval=0.02)
        return f"Typed: {text!r}"
    except Exception as e:
        return f"Could not type text: {e}"


@_catch_backend_unavailable
def keyboard_hotkey(keys: str) -> str:
    """Press a hotkey combination, e.g. 'ctrl+c' or 'alt+tab'."""
    pyautogui = _get_pyautogui()
    key_list = [k.strip() for k in keys.split("+") if k.strip()]
    if not key_list:
        return f"'{keys}' isn't a valid key combination."
    try:
        pyautogui.hotkey(*key_list)
        return f"Pressed hotkey: {keys}"
    except Exception as e:
        return f"Could not press hotkey '{keys}': {e}"


@_catch_backend_unavailable
def screen_size() -> str:
    """Return the screen resolution -- useful before picking click coordinates."""
    pyautogui = _get_pyautogui()
    try:
        width, height = pyautogui.size()
        return f"{width}x{height}"
    except Exception as e:
        return f"Could not get screen size: {e}"


DESKTOP_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": "Click the mouse at specific screen coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate in pixels."},
                    "y": {"type": "integer", "description": "Y coordinate in pixels."},
                    "button": {"type": "string", "description": "'left', 'right', or 'middle'. Defaults to left."},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_type",
            "description": "Type text at wherever the keyboard focus currently is.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to type."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_hotkey",
            "description": "Press a keyboard shortcut, e.g. 'ctrl+c', 'alt+tab', 'win+d'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "string", "description": "Keys joined by '+', e.g. 'ctrl+s'."},
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_size",
            "description": "Get the screen resolution in pixels -- useful for knowing valid click coordinates.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

DESKTOP_TOOL_FUNCTIONS = {
    "mouse_click": mouse_click,
    "keyboard_type": keyboard_type,
    "keyboard_hotkey": keyboard_hotkey,
    "screen_size": screen_size,
}

DESKTOP_RISKY_TOOLS = {"mouse_click", "keyboard_type", "keyboard_hotkey"}
