"""
Media playback control and now-playing info for Jarvis.

Platform-specific, like tools/window_control.py:
  - macOS: AppleScript via osascript, targeting Music.app.
  - Linux: playerctl (a common MPRIS CLI front-end -- must be installed
    separately; this doesn't bundle it, same pattern as every other
    optional external dependency in this codebase).
  - Windows: simulated hardware media keys (VK_MEDIA_PLAY_PAUSE etc. via
    keybd_event) for playback control, since there's no universal CLI
    for this on Windows; now-playing metadata uses the WinRT
    GlobalSystemMediaTransportControlsSessionManager API via the
    optional winsdk package, degrading gracefully if it isn't installed.

control_media is registered as risky: it's an input-simulation/app-
control action, the same risk class as desktop_control.py's mouse/
keyboard tools. get_now_playing is read-only.
"""

import platform
import subprocess

_ACTIONS = {"play_pause", "next", "previous", "volume_up", "volume_down", "mute"}


def _control_macos(action: str) -> str:
    # "playpause"/"next track"/"previous track" are Music.app's own verbs;
    # volume is a system-level AppleScript command, not app-specific.
    scripts = {
        "play_pause": 'tell application "Music" to playpause',
        "next": 'tell application "Music" to next track',
        "previous": 'tell application "Music" to previous track',
        "volume_up": "set volume output volume ((output volume of (get volume settings)) + 10)",
        "volume_down": "set volume output volume ((output volume of (get volume settings)) - 10)",
        "mute": "set volume with output muted",
    }
    subprocess.run(["osascript", "-e", scripts[action]], check=True, capture_output=True)
    return f"Sent '{action}' to Music.app."


def _control_linux(action: str) -> str:
    commands = {
        "play_pause": ["playerctl", "play-pause"],
        "next": ["playerctl", "next"],
        "previous": ["playerctl", "previous"],
        "volume_up": ["playerctl", "volume", "0.1+"],
        "volume_down": ["playerctl", "volume", "0.1-"],
        "mute": ["playerctl", "volume", "0"],
    }
    try:
        subprocess.run(commands[action], check=True, capture_output=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "playerctl is not installed. On most distros: sudo apt install playerctl "
            "(or the equivalent for your package manager)."
        ) from e
    return f"Sent '{action}' via playerctl."


def _control_windows(action: str) -> str:
    try:
        import ctypes
    except ImportError as e:
        raise RuntimeError("Media key simulation isn't available on this system.") from e

    # Virtual key codes for the standard multimedia keys.
    vk_codes = {
        "play_pause": 0xB3,  # VK_MEDIA_PLAY_PAUSE
        "next": 0xB0,        # VK_MEDIA_NEXT_TRACK
        "previous": 0xB1,    # VK_MEDIA_PREV_TRACK
        "volume_up": 0xAF,   # VK_VOLUME_UP
        "volume_down": 0xAE, # VK_VOLUME_DOWN
        "mute": 0xAD,        # VK_VOLUME_MUTE
    }
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    vk = vk_codes[action]
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
    return f"Sent media key for '{action}'."


def control_media(action: str) -> str:
    """Send a media control command: play_pause, next, previous, volume_up,
    volume_down, or mute."""
    action = (action or "").strip().lower()
    if action not in _ACTIONS:
        return f"'{action}' isn't a recognized action. Use one of: {', '.join(sorted(_ACTIONS))}."

    system = platform.system()
    try:
        if system == "Darwin":
            return _control_macos(action)
        elif system == "Windows":
            return _control_windows(action)
        else:
            return _control_linux(action)
    except RuntimeError as e:
        return str(e)
    except subprocess.CalledProcessError as e:
        return f"Media control command failed: {e}"
    except Exception as e:
        return f"Could not send media command '{action}': {e}"


def _now_playing_macos() -> str:
    script = (
        'tell application "Music"\n'
        "  if player state is playing then\n"
        '    return (name of current track) & " -- " & (artist of current track)\n'
        "  else\n"
        '    return "Nothing is currently playing."\n'
        "  end if\n"
        "end tell"
    )
    result = subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)
    return result.stdout.strip() or "Nothing is currently playing."


def _now_playing_linux() -> str:
    try:
        result = subprocess.run(
            ["playerctl", "metadata", "--format", "{{ title }} -- {{ artist }}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "playerctl is not installed. On most distros: sudo apt install playerctl."
        ) from e
    except subprocess.CalledProcessError:
        return "Nothing is currently playing."
    return result.stdout.strip() or "Nothing is currently playing."


def _now_playing_windows() -> str:
    try:
        import asyncio

        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )
    except ImportError as e:
        raise RuntimeError(
            "Now-playing info isn't available on Windows without the optional "
            "'winsdk' package. Run: pip install winsdk"
        ) from e

    async def _query():
        manager = await SessionManager.request_async()
        session = manager.get_current_session()
        if session is None:
            return "Nothing is currently playing."
        info = await session.try_get_media_properties_async()
        title = info.title or "(unknown title)"
        artist = info.artist or "(unknown artist)"
        return f"{title} -- {artist}"

    return asyncio.run(_query())


def get_now_playing() -> str:
    """Return the title/artist of whatever is currently playing, if anything."""
    system = platform.system()
    try:
        if system == "Darwin":
            return _now_playing_macos()
        elif system == "Windows":
            return _now_playing_windows()
        else:
            return _now_playing_linux()
    except RuntimeError as e:
        return str(e)
    except subprocess.CalledProcessError as e:
        return f"Could not read now-playing info: {e}"
    except Exception as e:
        return f"Could not read now-playing info: {e}"


MEDIA_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "control_media",
            "description": (
                "Control media playback: play/pause, skip to next/previous track, "
                "or adjust volume."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": sorted(_ACTIONS),
                        "description": "The media control action to perform.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_now_playing",
            "description": "Get the title and artist of whatever is currently playing, if anything.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

MEDIA_TOOL_FUNCTIONS = {
    "control_media": control_media,
    "get_now_playing": get_now_playing,
}

# control_media simulates input / drives whatever app is playing media --
# same risk class as desktop_control.py's mouse/keyboard tools.
# get_now_playing is read-only.
MEDIA_RISKY_TOOLS = {"control_media"}
