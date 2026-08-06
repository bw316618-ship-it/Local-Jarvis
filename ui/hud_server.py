"""
Local graphical HUD bridge for Jarvis.

Two things live here:

1. The original one-way state broadcast (idle/listening/thinking/
   speaking/tool/error) that the reactor/storm HUD renders -- unchanged
   in spirit from the first version of this file.

2. NEW: a full bidirectional chat channel. A JarvisLLM instance can be
   "attached" to this bridge (attach_jarvis()) so that messages typed
   into the HUD page are routed straight to jarvis.chat(), with replies,
   tool-step announcements, and risky-tool confirmation prompts all
   streamed back over the same WebSocket. This is what makes the HUD a
   real second way to talk to Jarvis, not just a display -- see
   jarvis_daemon.py, which runs a JarvisLLM with *only* this as its
   interface (no terminal input loop at all), so it can keep running,
   and keep the browser connected, independent of whether any terminal
   window is open.

Everything here is still best-effort and silently degrades: if the
servers can't bind their ports, or `websockets` isn't installed, or
nothing is connected yet, calls into this module are just no-ops --
Jarvis's actual functionality never depends on this running. The one new
exception is confirmation: if a risky tool call is triggered with no
JarvisLLM attached to route it, or no HUD client connected to answer it,
request_confirmation() times out and declines, the same fail-safe
default as an unanswered terminal prompt.
"""

import asyncio
import json
import threading
import uuid
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from config import CONFIG

STATIC_DIR = Path(__file__).resolve().parent / "hud" / "static"

HTTP_PORT = CONFIG["hud_http_port"]
WS_PORT = CONFIG["hud_ws_port"]

CONFIRM_TIMEOUT_SECONDS = 120  # how long a risky-tool prompt waits for a browser response


class HUDBridge:
    """Starts the local HTTP + WebSocket servers, lets the rest of Jarvis
    push state changes to any connected HUD tab, and (once a JarvisLLM is
    attached) routes chat messages typed into the HUD straight into it.

    Safe to call any of the public methods even if the servers never
    started, or nothing is connected -- everything degrades to a no-op
    rather than raising. start()/stop() are meant to be callable
    repeatedly across a session (the /hud toggle in main.py), not just
    once at startup.
    """

    def __init__(self, http_port: int = HTTP_PORT, ws_port: int = WS_PORT):
        self.http_port = http_port
        self.ws_port = ws_port

        self._loop = None
        self._clients = set()
        self._http_server = None
        self._ws_stop_signal = None
        self._available = False

        self._jarvis = None
        self._chat_lock = threading.Lock()  # JarvisLLM isn't written to be
        # called from more than one thread at once (it mutates
        # self.short_term); this serializes chat() calls that arrive
        # from the browser so two fast messages can't interleave.

        self._pending_confirms = {}  # id -> {"event": threading.Event, "approved": bool|None}
        self._pending_confirms_lock = threading.Lock()

    # -- Lifecycle -------------------------------------------------------

    def is_running(self) -> bool:
        return self._available

    def attach_jarvis(self, jarvis) -> None:
        """Wire a JarvisLLM instance up to this bridge so chat messages
        typed into the HUD get routed to it. Without this, the HUD still
        shows state changes (if something else calls set_state()), but
        typing into its chat box just gets a 'chat isn't available'
        response."""
        self._jarvis = jarvis

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
                # which is guaranteed here since this always runs off
                # the WebSocket server's own event-loop thread
                self._http_server.server_close()
            except Exception:
                pass
            self._http_server = None

        if self._loop is not None and self._ws_stop_signal is not None:
            try:
                self._loop.call_soon_threadsafe(self._ws_stop_signal.set)
            except Exception:
                pass

        # Release anything still waiting on a confirmation -- a stopped
        # HUD can never answer it, so default to declining rather than
        # hanging a tool call forever. Each waiting request_confirmation()
        # call pops its own entry once woken (see below) -- we only set
        # the values and wake it here, rather than clearing the dict
        # ourselves, so its own cleanup path runs normally instead of
        # racing this one.
        with self._pending_confirms_lock:
            for pending in self._pending_confirms.values():
                pending["approved"] = False
                pending["event"].set()

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

    # -- WebSocket: state broadcasts + bidirectional chat ----------------

    def _run_ws_server(self) -> None:
        import websockets

        async def handler(websocket):
            self._clients.add(websocket)
            try:
                async for raw_message in websocket:
                    await self._handle_incoming(raw_message)
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

    async def _handle_incoming(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message)
        except Exception:
            return  # malformed message from a client -- ignore, don't crash the server

        msg_type = data.get("type")

        if msg_type == "user_message":
            text = (data.get("text") or "").strip()
            if not text:
                return
            if self._jarvis is None:
                await self._broadcast_json({
                    "type": "chat_unavailable",
                    "text": (
                        "This HUD session isn't connected to a running Jarvis "
                        "(it was opened from the terminal CLI, which only "
                        "broadcasts state, not chat). Run jarvis_daemon.py "
                        "for browser chat."
                    ),
                })
                return
            # jarvis.chat() is a blocking call -- run it off the asyncio
            # loop's thread so it doesn't stall state broadcasts or other
            # clients' messages while this one is being answered.
            threading.Thread(target=self._handle_user_message, args=(text,), daemon=True).start()

        elif msg_type == "confirm_response":
            request_id = data.get("id")
            approved = bool(data.get("approved"))
            with self._pending_confirms_lock:
                pending = self._pending_confirms.get(request_id)
                if pending is not None:
                    pending["approved"] = approved
                    pending["event"].set()

    def _handle_user_message(self, text: str) -> None:
        """Runs jarvis.chat() on a worker thread (started from the
        asyncio recv handler) and broadcasts each callback as it fires."""
        with self._chat_lock:
            def on_step(message: str) -> None:
                self.broadcast_tool_step(message)

            def on_sentence(sentence: str) -> None:
                self.broadcast_reply_chunk(sentence)

            try:
                self._jarvis.chat(text, on_step=on_step, on_sentence=on_sentence)
            except Exception as e:
                self._broadcast({"type": "error", "text": f"Jarvis hit an error: {e}"})
            finally:
                self._broadcast({"type": "reply_done"})

    def _tool_name_from_step(self, message: str) -> str:
        body = message[len("Step: "):] if message.startswith("Step: ") else message
        return body.split("(")[0].strip()

    def broadcast_tool_step(self, message: str) -> None:
        if message.startswith("Plan:"):
            self._broadcast({"type": "plan", "text": message[len("Plan:"):].strip()})
            return
        name = self._tool_name_from_step(message)
        self.set_state("tool", {"name": name})
        self._broadcast({"type": "tool_step", "text": message})

    def broadcast_reply_chunk(self, sentence: str) -> None:
        self.set_state("speaking")
        self._broadcast({"type": "reply_chunk", "text": sentence})

    # -- Confirmation bridge: risky tools ask the browser instead of stdin --

    def request_confirmation(self, name: str, arguments: dict) -> bool:
        """Blocks the calling thread (the JarvisLLM tool-calling loop's
        thread) until a connected HUD client answers, or times out.
        Times out to declined -- same fail-safe default as an unanswered
        terminal prompt. Declines immediately if the HUD isn't running or
        nothing is connected, since there's no one to ask."""
        if not self._available or not self._clients:
            print(f"[Jarvis HUD] No HUD client connected to confirm '{name}' -- declining.")
            return False

        request_id = str(uuid.uuid4())
        event = threading.Event()
        with self._pending_confirms_lock:
            self._pending_confirms[request_id] = {"event": event, "approved": None}

        self._broadcast({"type": "confirm_request", "id": request_id, "tool": name, "args": arguments})

        answered = event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)

        with self._pending_confirms_lock:
            pending = self._pending_confirms.pop(request_id, None)

        if not answered or pending is None:
            print(f"[Jarvis HUD] Confirmation for '{name}' timed out -- declining.")
            return False

        return bool(pending["approved"])

    # -- Broadcasting helpers ---------------------------------------------

    async def _broadcast_json(self, payload: dict) -> None:
        await self._broadcast_raw(json.dumps(payload))

    async def _broadcast_raw(self, payload: str) -> None:
        if not self._clients:
            return
        for ws in list(self._clients):  # snapshot -- a client can disconnect mid-broadcast
            try:
                await ws.send(payload)
            except Exception:
                self._clients.discard(ws)

    def _broadcast(self, payload: dict) -> None:
        """Thread-safe broadcast callable from any thread (not just the
        asyncio loop's own) -- schedules the actual send onto the loop."""
        if not self._available or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast_json(payload), self._loop)
        except Exception:
            pass

    def set_state(self, state: str, meta: dict = None) -> None:
        """Broadcast a state change to any connected HUD tab.

        `state` is one of: 'idle', 'listening', 'thinking', 'speaking',
        'tool', 'error'. `meta` is optional extra context (e.g. the tool
        name during 'tool') -- the frontend isn't required to use it.
        """
        self._broadcast({"type": "state", "state": state, "meta": meta or {}})


# Module-level singleton -- one HUD bridge per Jarvis process, imported
# and used the same way memory/shared.py's embedder/client singletons are.
hud = HUDBridge()
