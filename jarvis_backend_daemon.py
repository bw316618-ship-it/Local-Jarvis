"""
Jarvis Backend daemon — Step 13.

Runs JarvisRuntime independently of the graphical HUD server.

Start:
    python jarvis_backend_daemon.py
"""

import threading

from brain.runtime import JarvisRuntime
from backend import JarvisBackend


def main():
    print("Starting Jarvis backend...")

    runtime = JarvisRuntime()
    backend = JarvisBackend(runtime=runtime)

    if not backend.start():
        print("Could not start Jarvis backend.")
        return

    print(
        f"Jarvis backend running on "
        f"WebSocket port {backend.ws_port}."
    )
    print(
        "This process owns the Jarvis runtime independently "
        "of the graphical HUD."
    )
    print("Press Ctrl+C to stop.")

    stop_event = threading.Event()

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        print("\nStopping Jarvis backend...")
        backend.stop()


if __name__ == "__main__":
    main()
