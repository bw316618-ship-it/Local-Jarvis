import os
import sys
import threading
from pathlib import Path

import pystray
import webview
from PIL import Image, ImageDraw

from brain.runtime import JarvisRuntime
from config import CONFIG
from tools.diagnostics import system_status_snapshot
from ui.hud_server import hud
from ui.native_overlay import NativeOverlay
from voice import session_state


HUD_URL = f"http://localhost:{CONFIG['hud_http_port']}/index.html"
_window = None
_overlay = None
_quitting = False

_AUTOSTART_NAME = "JarvisTray.vbs"


def _startup_dir():
    if sys.platform != "win32":
        return None

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None

    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def _autostart_path():
    startup_dir = _startup_dir()
    return None if startup_dir is None else startup_dir / _AUTOSTART_NAME


def _pythonw_path():
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def _is_autostart_enabled(item=None):
    path = _autostart_path()
    return path is not None and path.exists()


def _toggle_autostart(icon, item):
    if sys.platform != "win32":
        print("[Jarvis tray] Autostart is only implemented for Windows.")
        return

    path = _autostart_path()

    if path is None:
        print(
            "[Jarvis tray] Could not resolve the Startup folder "
            "(APPDATA not set) -- can't manage autostart."
        )
        return

    if path.exists():
        try:
            path.unlink()
            print("[Jarvis tray] Removed from Windows startup.")
        except OSError as exc:
            print(f"[Jarvis tray] Could not remove autostart entry: {exc}")
        return

    script_path = Path(__file__).resolve()
    pythonw = _pythonw_path()

    vbs = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        'WshShell.Run Chr(34) & "'
        f'{pythonw}" & Chr(34) & " " & Chr(34) & "{script_path}'
        '" & Chr(34), 0, False\n'
        "Set WshShell = Nothing\n"
    )

    try:
        path.write_text(vbs, encoding="utf-8")
        print("[Jarvis tray] Added to Windows startup.")
    except OSError as exc:
        print(f"[Jarvis tray] Could not write autostart entry: {exc}")


def _build_icon_image():
    size = 64
    img = Image.new("RGBA", (size, size), (10, 14, 18, 255))
    draw = ImageDraw.Draw(img)

    pad = 10

    draw.ellipse(
        [pad, pad, size - pad, size - pad],
        outline=(64, 220, 255, 255),
        width=6,
    )

    draw.ellipse(
        [
            size // 2 - 6,
            size // 2 - 6,
            size // 2 + 6,
            size // 2 + 6,
        ],
        fill=(64, 220, 255, 255),
    )

    return img


def _open_hud(icon=None, item=None):
    if _window is not None:
        _window.show()


def _toggle_overlay(icon, item):
    if _overlay is not None:
        _overlay.toggle_visible()


def _overlay_visible(item=None):
    return (
        _overlay is not None
        and _overlay._visible
    )


def _on_window_closing():
    if _quitting:
        return True

    if _window is not None:
        _window.hide()

    return False


def _toggle_mute(icon, item):
    if session_state.is_muted():
        session_state.unmute()
    else:
        session_state.mute()


def _mute_checked(item):
    return session_state.is_muted()


def _show_status(icon, item):
    snapshot = system_status_snapshot()

    cpu = snapshot.get("cpu_percent")
    memory = snapshot.get("memory_percent")
    disk = snapshot.get("disk_percent")

    lines = []

    if cpu is not None:
        lines.append(f"CPU {cpu:.0f}%")

    if memory is not None:
        lines.append(f"RAM {memory:.0f}%")

    if disk is not None:
        lines.append(f"Disk {disk:.0f}%")

    message = " | ".join(lines) if lines else "Status unavailable"

    try:
        icon.notify(message, title="Jarvis status")
    except Exception:
        print(f"[Jarvis tray] {message}")


def _quit(icon, item):
    global _quitting

    _quitting = True

    hud.stop()
    icon.stop()

    if _overlay is not None:
        _overlay.stop()

    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def _run_tray():
    menu = pystray.Menu(
        pystray.MenuItem(
            "Open HUD",
            _open_hud,
            default=True,
        ),
        pystray.MenuItem(
            "Show Overlay",
            _toggle_overlay,
            checked=_overlay_visible,
        ),
        pystray.MenuItem(
            "Mute",
            _toggle_mute,
            checked=_mute_checked,
        ),
        pystray.MenuItem(
            "Status",
            _show_status,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Start with Windows",
            _toggle_autostart,
            checked=_is_autostart_enabled,
            visible=sys.platform == "win32",
        ),
        pystray.MenuItem(
            "Quit",
            _quit,
        ),
    )

    icon = pystray.Icon(
        "jarvis",
        _build_icon_image(),
        "Jarvis",
        menu,
    )

    icon.run()


def main():
    global _window
    global _overlay

    print("Starting Jarvis tray app...")

    runtime = JarvisRuntime()
    hud.attach_runtime(runtime)

    started = hud.start(open_browser=False)

    if not started:
        print(
            "[Jarvis tray] Could not start the HUD server "
            "(see the error above) -- nothing for the tray app "
            "to show. Exiting."
        )
        return

    print(f"Jarvis tray running -- HUD available at {HUD_URL}")
    print("Right-click the tray icon for options.")

    _window = webview.create_window(
        "Jarvis",
        HUD_URL,
        width=1280,
        height=800,
        background_color="#0a0e12",
        hidden=True,
    )

    _window.events.closing += _on_window_closing

    _overlay = NativeOverlay(
        system_status_snapshot
    )

    _overlay.start()

    threading.Thread(
        target=_run_tray,
        daemon=True,
    ).start()

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()