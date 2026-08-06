"""
Jarvis daemon -- runs the actual assistant (JarvisLLM) plus the HUD
bridge as a standalone, long-running background process, independent of
any particular UI.

This is what makes "talk to Jarvis from the browser, close the terminal"
actually work: main.py's interactive CLI is the terminal-based way to
talk to Jarvis, with its own JarvisLLM instance living inside that same
process -- closing that terminal necessarily kills it, there's no way
around that from inside main.py. This script is the other way: it owns
its own JarvisLLM, has no console.input() loop of any kind, and hands
that JarvisLLM to the HUD bridge (ui/hud_server.py) so the browser page
becomes a full chat client, not just a state display. Risky tool calls
get confirmed by whichever HUD tab is connected instead of a terminal
prompt, since there is no terminal prompt here.

Usage:
    python3 jarvis_daemon.py

Runs in the foreground by default (Ctrl+C to stop) so its logs are
visible on first run -- useful for checking it started cleanly before
you rely on it. To let it keep running after closing the terminal that
launched it, background/detach it at the OS level:

    macOS/Linux:  nohup python3 jarvis_daemon.py > jarvis_daemon.log 2>&1 &
                  (check jarvis_daemon.log for the confirmation-prompt
                  and startup messages you'd otherwise see in the terminal)

    Windows:      pythonw jarvis_daemon.py
                  (runs with no console window at all; or from
                  PowerShell: Start-Process python -ArgumentList
                  'jarvis_daemon.py' -WindowStyle Hidden)

Python can't portably detach a process from its controlling terminal by
itself -- that's an OS-level operation and the mechanism differs by
platform -- so this script doesn't try to paper over that; it just stays
alive in the foreground until told to stop, the same as any other
long-running local service, and it's on you to background it with the
tools your OS provides if you want it to outlive the terminal that
started it.

Voice (/voice, /wake) and the terminal-only commands (/log, /save,
/insights, etc.) aren't available here -- those are main.py CLI
features, layered on top of JarvisLLM, not part of JarvisLLM itself.
This daemon exposes exactly what ui/hud_server.py's chat protocol
supports: plain text in, streamed replies out, plus confirmation
prompts for risky tools.
"""

import threading

from brain.llm import JarvisLLM
from ui.hud_server import hud


def _daemon_confirm(name: str, arguments: dict) -> bool:
    """Confirmation path for tool calls triggered from the browser --
    asks whichever HUD tab is connected and blocks until it answers, the
    same fail-safe-to-decline behavior as the terminal's confirm prompt,
    just carried over a WebSocket instead of stdin."""
    return hud.request_confirmation(name, arguments)


def main():
    print("Starting Jarvis daemon...")

    jarvis = JarvisLLM(confirm_callback=_daemon_confirm)
    hud.attach_jarvis(jarvis)

    started = hud.start(open_browser=True)
    if not started:
        print(
            "[Jarvis daemon] Could not start the HUD server (see the error "
            "above) -- there is no other interface in this script, so "
            "there's nothing for this daemon to do. Exiting."
        )
        return

    print(f"Jarvis daemon running -- chat at http://localhost:{hud.http_port}")
    print("Press Ctrl+C to stop.")

    stop_event = threading.Event()
    try:
        stop_event.wait()  # block forever; all real work happens in hud_server's own threads
    except KeyboardInterrupt:
        print("\nStopping Jarvis daemon...")
        hud.stop()


if __name__ == "__main__":
    main()
