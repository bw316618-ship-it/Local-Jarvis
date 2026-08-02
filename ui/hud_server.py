"""
Local graphical HUD bridge for Jarvis -- Phase 2 of the visual identity
work started in ui/splash.py (terminal boot animation) and
ui/thinking.py (terminal thinking pulse). This is the first step toward
a real graphical HUD living outside the terminal: a small local web page
(served only on this machine, nothing external) showing the same
rotating-ring visual language, driven by state changes Jarvis broadcasts
over a local WebSocket as it works.

Architecture, and why:
- A local browser tab, not a native window toolkit (e.g. pywebview) --
  keeps this dependency-free (stdlib http.server, plus the `websockets`
  package Jarvis already depends on transitively -- see
  requirements.txt). A native embedded window is a reasonable later
  upgrade once the web version proves out the visual design, not a
  prerequisite for it.
- WebSocket push, not polling -- the HUD should react the instant
  Jarvis's state changes (idle -> thinking -> speaking -> tool -> idle),
  not on a timer. A single broadcast channel keeps every connected tab
  in sync if more than one happens to be open.
- Static HTTP server for the page itself, separate from the WebSocket --
  simplest possible split: HTTP hands out index.html/hud.js/hud.css
  once; the WebSocket only ever carries small JSON state messages after
  that, so the animation loop lives entirely in the browser's own
  requestAnimationFrame, not tied to anything in this Python process.

Everything here is best-effort and silently degrades: if the servers
can't bind their ports, or `websockets` isn't installed, or nothing is
connected yet, set_state() calls are just no-ops -- Jarvis's actual
functionality never depends on this running.
"""

import asyncio
import json
import threading
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from config import CONFIG

STATIC_DIR = Path(__file__).resolve().parent / "hud" / "static"

# Fallback constants, kept for anyone importing HUDBridge directly rather
# than the module-level `hud` singleton below -- the singleton itself
# reads from CONFIG so ports are overridable via jarvis_config.json like
# every other tunable in the project.
HTTP_PORT = CONFIG["hud_http_port"]
WS_PORT = CONFIG["hud_ws_port"]


class HUDBridge:
    """Starts the local HTTP + WebSocket servers, and lets the rest of
    Jarvis push state changes to any connected HUD tab via set_state().

    Safe to call set_state() even if nothing is connected, or if the
    servers never started (missing `websockets` package, ports taken,
    etc.) -- it just no-ops in that case. start()/stop() are meant to be
    called repeatedly across a session (e.g. a /hud toggle command), not
    just once at startup.
    """

    def __init__(self, http_port: int = HTTP_PORT, ws_port: int = WS_PORT):
        self.http_port = http_port
        self.ws_port = ws_port

        self._loop = None
        self._clients = set()
        self._http_server = None
        self._ws_stop_signal = None
        self._available = False

    def is_running(self) -> bool:
        return self._available

    def start(self, open_browser: bool = True) -> bool:
        """Start both servers in background threads. Never raises -- a
        failure here just means the HUD isn't available this session.
        Returns True if it actually started (or was already running),
        False if it couldn't (e.g. `websockets` missing)."""
        if self._available:
            if open_browser:
                webbrowser.open(f"http://localhost:{self.http_port}/index.html")
            return True

        try:
            import websockets  # noqa: F401 -- imported here so a missing
            # package degrades only this feature, not all of Jarvis
        except ImportError:
            print("[Jarvis HUD] 'websockets' package not installed -- graphical HUD disabled.")
            return False

        threading.Thread(target=self._run_http_server, daemon=True).start()
        threading.Thread(target=self._run_ws_server, daemon=True).start()

        self._available = True

        if open_browser:
            webbrowser.open(f"http://localhost:{self.http_port}/index.html")

        return True

    def stop(self) -> None:
        """Shut down both servers cleanly. Safe to call even if the HUD
        was never started, or is already stopped."""
        if not self._available:
            return

        if self._http_server is not None:
            try:
                self._http_server.shutdown()  # blocks briefly; must be
                # called from a different thread than serve_forever(),
                # which is guaranteed here since this runs on the main
                # console thread and serve_forever() is in its own daemon
                self._http_server.server_close()
            except Exception:
                pass
            self._http_server = None

        if self._loop is not None and self._ws_stop_signal is not None:
            try:
                self._loop.call_soon_threadsafe(self._ws_stop_signal.set)
            except Exception:
                pass

        self._loop = None
        self._ws_stop_signal = None
        self._clients = set()
        self._available = False

    # -- HTTP: serves the static HUD page -----------------------------

    def _run_http_server(self) -> None:
        try:
            handler = partial(SimpleHTTPRequestHandler, directory=str(STATIC_DIR))
            self._http_server = ThreadingHTTPServer(("localhost", self.http_port), handler)
            self._http_server.serve_forever()
        except Exception as e:
            print(f"[Jarvis HUD] Static server failed to start: {e}")

    # -- WebSocket: pushes state changes to connected tabs -------------

    def _run_ws_server(self) -> None:
        import websockets

        async def handler(websocket):
            self._clients.add(websocket)
            try:
                async for _ in websocket:
                    pass  # the HUD is display-only; it never sends us anything
            finally:
                self._clients.discard(websocket)

        async def serve():
            self._ws_stop_signal = asyncio.Event()
            async with websockets.serve(handler, "localhost", self.ws_port):
                await self._ws_stop_signal.wait()  # runs until stop() signals it

        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(serve())
        except Exception as e:
            print(f"[Jarvis HUD] WebSocket server failed to start: {e}")

    async def _broadcast(self, payload: str) -> None:
        if not self._clients:
            return
        for ws in list(self._clients):  # snapshot -- a client can disconnect mid-broadcast
            try:
                await ws.send(payload)
            except Exception:
                self._clients.discard(ws)

    def set_state(self, state: str, meta: dict = None) -> None:
        """Broadcast a state change to any connected HUD tab.

        `state` is one of: 'idle', 'listening', 'thinking', 'speaking',
        'tool', 'error'. `meta` is optional extra context (e.g. the tool
        name during 'tool') -- the frontend isn't required to use it.
        """
        if not self._available or self._loop is None:
            return

        payload = json.dumps({"state": state, "meta": meta or {}})
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(payload), self._loop)
        except Exception:
            pass


# Module-level singleton -- one HUD bridge per Jarvis process, imported
# and used the same way memory/shared.py's embedder/client singletons are.
hud = HUDBridge()
