"""
Window management for Jarvis, via PyGetWindow.

Complements tools/desktop_control.py (raw mouse/keyboard at coordinates)
with window-level control: listing open windows, focusing one by title,
minimizing, closing. This is what lets "open Chrome and switch to it" or
"focus my code editor" work reliably, rather than guessing coordinates.

The import is deferred into _get_gw() because PyGetWindow raises
NotImplementedError at *import time* on unsupported platforms (it only
supports Windows and macOS, not Linux) -- deferring means the rest of
Jarvis still works even where this specific capability isn't available.
"""


def _get_gw():
    try:
        import pygetwindow as gw
    except (ImportError, NotImplementedError, OSError) as e:
        raise RuntimeError(
            "Window control isn't available: PyGetWindow doesn't support "
            "this operating system (Windows and macOS only), or isn't "
            "installed. Run: pip install -r requirements.txt"
        ) from e
    return gw


def list_windows() -> str:
    """List the titles of all currently open windows."""
    try:
        gw = _get_gw()
        titles = [t for t in gw.getAllTitles() if t.strip()]
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Could not list windows: {e}"

    if not titles:
        return "No open windows found."
    return "Open windows:\n" + "\n".join(f"- {t}" for t in titles)


def focus_window(title_substring: str) -> str:
    """Bring the first window matching `title_substring` to the front."""
    try:
        gw = _get_gw()
        matches = gw.getWindowsWithTitle(title_substring)
        if not matches:
            return f"No open window found matching '{title_substring}'."
        window = matches[0]
        window.activate()
        return f"Focused '{window.title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Could not focus a window matching '{title_substring}': {e}"


def minimize_window(title_substring: str) -> str:
    """Minimize the first window matching `title_substring`."""
    try:
        gw = _get_gw()
        matches = gw.getWindowsWithTitle(title_substring)
        if not matches:
            return f"No open window found matching '{title_substring}'."
        window = matches[0]
        window.minimize()
        return f"Minimized '{window.title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Could not minimize a window matching '{title_substring}': {e}"


def close_window(title_substring: str) -> str:
    """Close the first window matching `title_substring`. Can lose unsaved work."""
    try:
        gw = _get_gw()
        matches = gw.getWindowsWithTitle(title_substring)
        if not matches:
            return f"No open window found matching '{title_substring}'."
        window = matches[0]
        window.close()
        return f"Closed '{window.title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Could not close a window matching '{title_substring}': {e}"


WINDOW_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "List the titles of all currently open windows on the desktop.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Bring a window to the front and give it keyboard focus, matched by a substring of its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_substring": {"type": "string", "description": "Text that appears in the target window's title, e.g. 'Chrome' or 'Visual Studio Code'."},
                },
                "required": ["title_substring"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "minimize_window",
            "description": "Minimize a window, matched by a substring of its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_substring": {"type": "string", "description": "Text that appears in the target window's title."},
                },
                "required": ["title_substring"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_window",
            "description": "Close a window, matched by a substring of its title. This can lose unsaved work in that window -- use with care.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_substring": {"type": "string", "description": "Text that appears in the target window's title."},
                },
                "required": ["title_substring"],
            },
        },
    },
]

WINDOW_TOOL_FUNCTIONS = {
    "list_windows": list_windows,
    "focus_window": focus_window,
    "minimize_window": minimize_window,
    "close_window": close_window,
}

# list_windows is read-only. Focusing/minimizing/closing change what's
# happening on screen (closing especially can lose unsaved work), so those
# confirm first -- consistent with mouse_click/keyboard_type in
# desktop_control.py.
WINDOW_RISKY_TOOLS = {"focus_window", "minimize_window", "close_window"}
