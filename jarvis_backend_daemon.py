"""
Jarvis Backend daemon — Step 14.2

Single launcher for both the phone/PC device backend (backend.py) and the
graphical HUD (ui/hud_server.py). Both are handed the SAME JarvisRuntime,
so they're the one Jarvis rather than two independent assistants with
their own LLM/memory/state.

(Previously this and jarvis_daemon.py each built their own JarvisRuntime.
Running both at once meant the HUD and any paired phone/PC were silently
talking to two different Jarvis instances -- the HUD would never see
state updates or replies for messages sent from a paired device, and
vice versa. Use this as your one launcher; don't also run
jarvis_daemon.py alongside it.)

Note: backend.py gives every *additional* connected device (beyond the
first to authenticate) its own isolated runtime, so multiple phones/PCs
pairing with Jarvis don't bleed conversation context into each other.
The runtime built here is the one the HUD shares with whichever device
authenticates first.

Start:
    python jarvis_backend_daemon.py
"""

import threading

from brain.runtime import JarvisRuntime
from backend import JarvisBackend
from ui.hud_server import hud


def main():
    print("Starting Jarvis backend...")

    runtime = JarvisRuntime()

    # Both interfaces use the SAME Jarvis runtime.
    backend = JarvisBackend(runtime=runtime)
    hud.attach_runtime(runtime)

    if not hud.start(open_browser=True):
        print("Could not start Jarvis HUD.")
        return

    if not backend.start():
        print("Could not start Jarvis backend.")
        hud.stop()
        return

    print(f"Jarvis backend running on WebSocket port {backend.ws_port}.")
    print("Jarvis backend and HUD share the same Jarvis runtime.")
    print(f"Jarvis HUD running on HTTP port {hud.http_port}.")
    print("Press Ctrl+C to stop.")

    stop_event = threading.Event()

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        print("\nStopping Jarvis...")
        backend.stop()
        hud.stop()


if __name__ == "__main__":
    main()
