"""
Jarvis daemon — Step 12.

The daemon owns the transport-independent JarvisRuntime and attaches that
runtime to the HUD bridge. The HUD is now a presentation/transport layer;
it no longer constructs JarvisSession or reaches into brain.* directly.
"""

import threading

from brain.runtime import JarvisRuntime
from ui.hud_server import hud


def main():
    print("Starting Jarvis daemon...")

    runtime = JarvisRuntime()
    hud.attach_runtime(runtime)

    started = hud.start(open_browser=True)
    if not started:
        print(
            "[Jarvis daemon] Could not start the HUD server (see the error "
            "above) -- there is no other interface in this script, so "
            "there's nothing for this daemon to do. Exiting."
        )
        return

    print(
        f"Jarvis daemon running -- chat at "
        f"http://localhost:{hud.http_port}"
    )
    print("Jarvis core runtime is independent of the HUD transport.")
    print("Press Ctrl+C to stop.")

    stop_event = threading.Event()

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        print("\nStopping Jarvis daemon...")
        hud.stop()


if __name__ == "__main__":
    main()
