"""
Local graphical HUD bridge for Jarvis.

Step 10/11:
- Device-aware WebSocket registry.
- LAN devices are NOT trusted merely because they can reach the port.
- Localhost PC can bootstrap itself.
- Unknown LAN devices require approval from an authenticated device.
- Approved devices receive a random bearer token.
- Only SHA-256 token hashes are persisted.
- Revoking a device invalidates its token.

Trust database:
    jarvis_hud_devices.json

This file is outside ui/hud/static so the HTTP server cannot serve it.
"""

import asyncio
import hashlib
import json
import secrets
import threading
import uuid
import webbrowser
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from config import CONFIG
from tools.diagnostics import system_status_snapshot
from tools.map_hud import drain_map_actions

STATIC_DIR = Path(__file__).resolve().parent / "hud" / "static"
TRUST_DB = Path(__file__).resolve().parent / "jarvis_hud_devices.json"

HTTP_PORT = CONFIG["hud_http_port"]
WS_PORT = CONFIG["hud_ws_port"]

CONFIRM_TIMEOUT_SECONDS = 120
AUTH_TIMEOUT_SECONDS = 15
PAIRING_TIMEOUT_SECONDS = 120
SYSTEM_STATUS_INTERVAL_SECONDS = CONFIG.get("hud_system_status_interval_seconds", 5)


def _hash_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


class _StaticFileHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler, but with .js/.mjs (and a few other
    types the HUD actually serves) hardcoded rather than left to
    mimetypes.guess_type()'s platform-dependent fallback.

    SimpleHTTPRequestHandler.extensions_map only hardcodes compression
    extensions (.gz, .bz2, .xz, .Z) -- everything else, including .js,
    falls through to mimetypes.guess_type(), which on Windows partly
    sources its answers from the registry (HKEY_CLASSES_ROOT). On a
    non-trivial number of real Windows machines that registry entry for
    .js is missing or has been overwritten by other installed software,
    so guess_type() returns something other than a JS MIME type -- most
    often text/plain.

    Classic <script src="...">  tags don't care what Content-Type they
    were served with and run regardless. type="module" scripts do:
    browsers strictly reject a module script whose response
    Content-Type isn't a JavaScript MIME type, and they do this
    silently from Python's point of view -- the browser console shows
    "Failed to load module script: Expected a JavaScript module script
    but the server responded with a MIME type of ...", but the HTTP
    request itself succeeds (200 OK) and nothing here would print an
    error. That's exactly the shape of "everything else in the HUD
    works, the three.js/storm3d.js path just silently never activates".

    storm3d.js is the only module-script entry point today, but the
    fix hardcodes the map rather than special-casing that one file so
    any future module script (or nested import under vendor/three/)
    is covered the same way without relying on the host OS's registry
    being in a good state.
    """

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".wasm": "application/wasm",
    }


class HUDBridge:
    """Local HTTP + authenticated WebSocket bridge."""

    def __init__(
        self,
        http_port: int = HTTP_PORT,
        ws_port: int = WS_PORT,
    ):
        self.http_port = http_port
        self.ws_port = ws_port

        self._loop = None
        self._clients = set()

        # websocket -> authenticated device
        self._devices = {}

        # device_id -> websocket
        self._device_clients = {}

        self._device_lock = threading.RLock()

        self._trusted = self._load_trusted()
        self._trust_lock = threading.RLock()

        # request_id -> {
        #   websocket: websocket,
        #   device: device
        # }
        self._pending_access = {}
        self._pending_access_lock = threading.RLock()

        self._http_server = None
        self._ws_stop_signal = None
        self._available = False

        self._runtime = None
        self._chat_lock = threading.Lock()

        self._pending_confirms = {}
        self._pending_confirms_lock = threading.Lock()

    # -- Trust database --------------------------------------------------

    def _load_trusted(self):
        if not TRUST_DB.exists():
            return {}

        try:
            data = json.loads(
                TRUST_DB.read_text(
                    encoding="utf-8"
                )
            )

            return (
                data
                if isinstance(data, dict)
                else {}
            )
        except Exception as e:
            print(
                f"[Jarvis HUD] Could not read "
                f"trust database: {e}"
            )
            return {}

    def _save_trusted(self):
        tmp = TRUST_DB.with_suffix(".tmp")

        tmp.write_text(
            json.dumps(
                self._trusted,
                indent=2,
            ),
            encoding="utf-8",
        )

        tmp.replace(TRUST_DB)

    def _is_trusted(self, device_id):
        with self._trust_lock:
            return device_id in self._trusted

    def _create_trusted_device(
        self,
        device,
        token,
    ):
        with self._trust_lock:
            self._trusted[
                device["device_id"]
            ] = {
                "device_id":
                    device["device_id"],
                "device_type":
                    device["device_type"],
                "name":
                    device["name"],
                "token_hash":
                    _hash_token(token),
                "created_at":
                    datetime.now().isoformat(),
            }

            self._save_trusted()

    def _authenticate_token(
        self,
        device_id,
        token,
    ):
        if not device_id or not token:
            return False

        with self._trust_lock:
            record = self._trusted.get(
                device_id
            )

            if not record:
                return False

            stored_hash = record.get(
                "token_hash",
                "",
            )

            return secrets.compare_digest(
                stored_hash,
                _hash_token(token),
            )

    def trusted_devices(self):
        with self._trust_lock:
            return [
                {
                    "device_id":
                        item["device_id"],
                    "device_type":
                        item["device_type"],
                    "name":
                        item["name"],
                }
                for item in self._trusted.values()
            ]

    def revoke_device(
        self,
        device_id,
    ):
        with self._trust_lock:
            existed = (
                device_id
                in self._trusted
            )

            if existed:
                del self._trusted[
                    device_id
                ]
                self._save_trusted()

        if not existed:
            return False

        with self._device_lock:
            websocket = (
                self._device_clients.get(
                    device_id
                )
            )

        if websocket is not None:
            self._send_to_socket(
                websocket,
                {
                    "type":
                        "device_revoked",
                    "device_id":
                        device_id,
                },
            )

            self._close_socket(
                websocket
            )

        self._broadcast_device_registry()

        return True

    # -- Lifecycle -------------------------------------------------------

    def is_running(self):
        return self._available

    def attach_runtime(self, runtime):
        """Attach the transport-independent Jarvis runtime."""
        self._runtime = runtime

    # Backward-compatible alias for existing callers.
    def attach_jarvis(self, jarvis):
        self.attach_runtime(jarvis)

    def start(
        self,
        open_browser=True,
    ):
        if self._available:
            if open_browser:
                webbrowser.open(
                    f"http://localhost:"
                    f"{self.http_port}/index.html"
                )

            return True

        try:
            import websockets
        except ImportError:
            print(
                "[Jarvis HUD] 'websockets' package "
                "not installed -- graphical HUD disabled."
            )
            return False

        threading.Thread(
            target=self._run_http_server,
            daemon=True,
        ).start()

        threading.Thread(
            target=self._run_ws_server,
            daemon=True,
        ).start()

        self._available = True

        if open_browser:
            webbrowser.open(
                f"http://localhost:"
                f"{self.http_port}/index.html"
            )

        return True

    def stop(self):
        if not self._available:
            return

        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception:
                pass

            self._http_server = None

        if (
            self._loop is not None
            and self._ws_stop_signal is not None
        ):
            try:
                self._loop.call_soon_threadsafe(
                    self._ws_stop_signal.set
                )
            except Exception:
                pass

        with self._pending_confirms_lock:
            for pending in (
                self._pending_confirms.values()
            ):
                pending["approved"] = False
                pending["event"].set()

        with self._device_lock:
            self._devices.clear()
            self._device_clients.clear()

        self._loop = None
        self._ws_stop_signal = None
        self._clients = set()
        self._available = False

    # -- HTTP ------------------------------------------------------------

    def _run_http_server(self):
        try:
            handler = partial(
                _StaticFileHandler,
                directory=str(STATIC_DIR),
            )

            self._http_server = (
                ThreadingHTTPServer(
                    ("0.0.0.0", self.http_port),
                    handler,
                )
            )

            self._http_server.serve_forever()

        except Exception as e:
            print(
                f"[Jarvis HUD] Static server "
                f"failed to start: {e}"
            )

    # -- Authentication --------------------------------------------------

    def _peer_is_local(self, websocket):
        try:
            peer = websocket.remote_address
            host = (
                peer[0]
                if isinstance(peer, tuple)
                else str(peer)
            )

            return host in {
                "127.0.0.1",
                "::1",
                "localhost",
            }

        except Exception:
            return False

    def _authenticated_clients(self):
        with self._device_lock:
            return list(
                self._devices.keys()
            )

    def _register_authenticated(
        self,
        websocket,
        device,
    ):
        with self._device_lock:
            old_socket = (
                self._device_clients.get(
                    device["device_id"]
                )
            )

            if (
                old_socket is not None
                and old_socket is not websocket
            ):
                self._devices.pop(
                    old_socket,
                    None
                )

                self._clients.discard(
                    old_socket
                )

            self._devices[websocket] = dict(
                device
            )

            self._device_clients[
                device["device_id"]
            ] = websocket

    async def _authenticate_connection(
        self,
        websocket,
        data,
    ):
        device_id = str(
            data.get("device_id")
            or ""
        ).strip()

        device_type = str(
            data.get("device_type")
            or ""
        ).strip().lower()

        name = str(
            data.get("name")
            or ""
        ).strip()

        token = str(
            data.get("token")
            or ""
        ).strip()

        if not device_id:
            await self._send_json(
                websocket,
                {
                    "type":
                        "auth_error",
                    "text":
                        "Missing device ID.",
                },
            )
            return False

        if device_type not in {
            "pc",
            "phone",
        }:
            device_type = "unknown"

        if not name:
            name = device_type.upper()

        device = {
            "device_id":
                device_id,
            "device_type":
                device_type,
            "name":
                name,
        }

        # The local Jarvis PC is the bootstrap authority.
        if self._peer_is_local(
            websocket
        ):
            if self._is_trusted(
                device_id
            ):
                if not self._authenticate_token(
                    device_id,
                    token,
                ):
                    await self._send_json(
                        websocket,
                        {
                            "type":
                                "auth_required",
                            "text":
                                "A valid device token is required.",
                        },
                    )
                    return False

                await self._send_json(
                    websocket,
                    {
                        "type":
                            "auth_granted",
                        "device":
                            device,
                    },
                )

            else:
                new_token = (
                    secrets.token_urlsafe(
                        32
                    )
                )

                self._create_trusted_device(
                    device,
                    new_token,
                )

                await self._send_json(
                    websocket,
                    {
                        "type":
                            "auth_granted",
                        "device":
                            device,
                        "token":
                            new_token,
                        "bootstrap":
                            True,
                    },
                )

            self._register_authenticated(
                websocket,
                device,
            )

            return True

        # LAN device that already has a valid token.
        if self._authenticate_token(
            device_id,
            token,
        ):
            await self._send_json(
                websocket,
                {
                    "type":
                        "auth_granted",
                    "device":
                        device,
                },
            )

            self._register_authenticated(
                websocket,
                device,
            )

            return True

        # Unknown LAN device: request approval.
        request_id = str(
            uuid.uuid4()
        )

        with self._pending_access_lock:
            self._pending_access[
                request_id
            ] = {
                "websocket":
                    websocket,
                "device":
                    device,
            }

        trusted_clients = (
            self._authenticated_clients()
        )

        if not trusted_clients:
            await self._send_json(
                websocket,
                {
                    "type":
                        "auth_pending",
                    "request_id":
                        request_id,
                    "text":
                        "No trusted Jarvis device "
                        "is available to approve this device.",
                },
            )

            return False

        request = {
            "type":
                "device_access_request",
            "request_id":
                request_id,
            "device":
                device,
        }

        for client in trusted_clients:
            await self._send_json(
                client,
                request
            )

        await self._send_json(
            websocket,
            {
                "type":
                    "auth_pending",
                "request_id":
                    request_id,
                "text":
                    "Waiting for approval from a trusted Jarvis device.",
            },
        )

        return False

    # -- WebSocket -------------------------------------------------------

    async def _system_status_loop(self):
        """Broadcast a live system-status snapshot (CPU/memory/disk/uptime)
        to every connected device every SYSTEM_STATUS_INTERVAL_SECONDS.

        This is the previously-unimplemented half of the HUD's "System
        Status" widget -- the frontend markup/CSS shell existed, but
        nothing on the backend ever actually pushed real data into it.
        psutil.cpu_percent(interval=0.5) blocks the calling thread for
        0.5s to measure over a sampling window, which is why this runs on
        a background thread via asyncio.to_thread rather than directly on
        the event loop -- otherwise every single status tick would stall
        the WebSocket server from handling anything else (chat messages,
        confirmations, device auth) for half a second, every
        SYSTEM_STATUS_INTERVAL_SECONDS.

        Waits on _ws_stop_signal with a timeout instead of a flat
        asyncio.sleep so shutdown isn't delayed by up to
        SYSTEM_STATUS_INTERVAL_SECONDS when stop() is called.
        """
        while not self._ws_stop_signal.is_set():
            try:
                snapshot = await asyncio.to_thread(system_status_snapshot)
                await self._broadcast_json({"type": "system_status", **snapshot})
            except Exception as e:
                print(f"[Jarvis HUD] System status broadcast failed: {e}")

            try:
                await asyncio.wait_for(
                    self._ws_stop_signal.wait(),
                    timeout=SYSTEM_STATUS_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                pass  # normal -- just means it's time for the next snapshot

    def _run_ws_server(self):
        import websockets

        async def handler(websocket):
            self._clients.add(
                websocket
            )

            authenticated = False

            try:
                try:
                    raw = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=AUTH_TIMEOUT_SECONDS,
                    )

                    data = json.loads(raw)

                except Exception:
                    return

                if data.get(
                    "type"
                ) != "authenticate":
                    await self._send_json(
                        websocket,
                        {
                            "type":
                                "auth_error",
                            "text":
                                "Authentication is required.",
                        },
                    )

                    return

                authenticated = (
                    await self._authenticate_connection(
                        websocket,
                        data,
                    )
                )

                if not authenticated:
                    # A pending/denied client never gets access to the
                    # command channel. Close it after the pairing window.
                    await asyncio.sleep(
                        PAIRING_TIMEOUT_SECONDS
                    )

                    return

                await self._send_json(
                    websocket,
                    {
                        "type":
                            "device_registry",
                        "devices":
                            self.connected_devices(),
                    },
                )

                async for raw_message in websocket:
                    await self._handle_incoming(
                        websocket,
                        raw_message,
                    )

            finally:
                self._unregister_client(
                    websocket
                )

                self._clients.discard(
                    websocket
                )

                await self._broadcast_json(
                    {
                        "type":
                            "device_registry",
                        "devices":
                            self.connected_devices(),
                    }
                )

        async def serve():
            self._ws_stop_signal = (
                asyncio.Event()
            )

            status_task = asyncio.create_task(
                self._system_status_loop()
            )

            try:
                async with websockets.serve(
                    handler,
                    "0.0.0.0",
                    self.ws_port,
                ):
                    await self._ws_stop_signal.wait()
            finally:
                status_task.cancel()
                try:
                    await status_task
                except asyncio.CancelledError:
                    pass

        try:
            self._loop = (
                asyncio.new_event_loop()
            )

            asyncio.set_event_loop(
                self._loop
            )

            self._loop.run_until_complete(
                serve()
            )

        except Exception as e:
            print(
                f"[Jarvis HUD] WebSocket server "
                f"failed to start: {e}"
            )

    async def _handle_incoming(
        self,
        websocket,
        raw_message,
    ):
        try:
            data = json.loads(
                raw_message
            )
        except Exception:
            return

        msg_type = data.get(
            "type"
        )

        # Only authenticated sockets reach this method.
        if msg_type == "device_approval":
            request_id = data.get(
                "request_id"
            )

            approved = bool(
                data.get(
                    "approved"
                )
            )

            if (
                self._device_for_websocket(
                    websocket
                )
                is None
            ):
                return

            with self._pending_access_lock:
                pending = (
                    self._pending_access.pop(
                        request_id,
                        None,
                    )
                )

            if pending is None:
                return

            target = pending[
                "websocket"
            ]

            device = pending[
                "device"
            ]

            if not approved:
                await self._send_json(
                    target,
                    {
                        "type":
                            "auth_denied",
                        "text":
                            "Device access was denied.",
                    },
                )

                self._close_socket(
                    target
                )

                return

            token = (
                secrets.token_urlsafe(
                    32
                )
            )

            self._create_trusted_device(
                device,
                token,
            )

            await self._send_json(
                target,
                {
                    "type":
                        "auth_granted",
                    "device":
                        device,
                    "token":
                        token,
                },
            )

            # The target receives the token, stores it, then reconnects.
            self._close_socket(
                target
            )

            return

        if msg_type == "revoke_device":
            if (
                self._device_for_websocket(
                    websocket
                )
                is None
            ):
                return

            self.revoke_device(
                str(
                    data.get(
                        "device_id"
                    )
                    or ""
                )
            )

            return

        if msg_type == "user_message":
            text = (
                data.get("text")
                or ""
            ).strip()

            if not text:
                return

            if self._runtime is None:
                await self._send_json(
                    websocket,
                    {
                        "type":
                            "chat_unavailable",
                        "text":
                            (
                                "This HUD session isn't "
                                "connected to a running Jarvis "
                                "(it was opened from the terminal "
                                "CLI, which only broadcasts state, "
                                "not chat). Run jarvis_daemon.py "
                                "for browser chat."
                            ),
                    },
                )

                return

            threading.Thread(
                target=self._handle_user_message,
                args=(
                    text,
                    data.get("map_context"),
                ),
                daemon=True,
            ).start()

            return

        if msg_type == "confirm_response":
            request_id = data.get(
                "id"
            )

            approved = bool(
                data.get(
                    "approved"
                )
            )

            with self._pending_confirms_lock:
                pending = (
                    self._pending_confirms.get(
                        request_id
                    )
                )

                if pending is not None:
                    pending["approved"] = (
                        approved
                    )

                    pending["event"].set()

    # -- Device registry -------------------------------------------------

    def _unregister_client(
        self,
        websocket,
    ):
        with self._device_lock:
            device = self._devices.pop(
                websocket,
                None
            )

            if device:
                device_id = device[
                    "device_id"
                ]

                if (
                    self._device_clients.get(
                        device_id
                    )
                    is websocket
                ):
                    self._device_clients.pop(
                        device_id,
                        None,
                    )

    def _device_for_websocket(
        self,
        websocket,
    ):
        with self._device_lock:
            device = self._devices.get(
                websocket
            )

            return (
                dict(device)
                if device
                else None
            )

    def connected_devices(self):
        with self._device_lock:
            return [
                dict(device)
                for device
                in self._devices.values()
            ]

    def send_to_device(
        self,
        device_id,
        payload,
    ):
        with self._device_lock:
            websocket = (
                self._device_clients.get(
                    device_id
                )
            )

        if websocket is None:
            return False

        return self._send_to_socket(
            websocket,
            payload,
        )

    def send_to_type(
        self,
        device_type,
        payload,
    ):
        device_type = str(
            device_type
        ).lower()

        with self._device_lock:
            sockets = [
                websocket
                for websocket, device
                in self._devices.items()
                if device[
                    "device_type"
                ] == device_type
            ]

        sent = 0

        for websocket in sockets:
            if self._send_to_socket(
                websocket,
                payload,
            ):
                sent += 1

        return sent

    def _broadcast_device_registry(
        self
    ):
        self._broadcast(
            {
                "type":
                    "device_registry",
                "devices":
                    self.connected_devices(),
            }
        )

    # -- Chat ------------------------------------------------------------

    def _handle_user_message(
        self,
        text,
        map_context=None,
    ):
        with self._chat_lock:
            if self._runtime is None:
                self._broadcast(
                    {
                        "type": "chat_unavailable",
                        "text": (
                            "This HUD session isn't "
                            "connected to a running Jarvis."
                        ),
                    }
                )
                return

            runtime_text = text

            if isinstance(map_context, dict):
                try:
                    runtime_text = (
                        f"{text}\n\n"
                        "[HUD MAP CONTEXT]\n"
                        f"{json.dumps(map_context)}\n"
                        "[END HUD MAP CONTEXT]"
                    )
                except Exception:
                    runtime_text = text

            try:
                self._runtime.handle_message(
                    runtime_text,
                    hud=self,
                )

                for action in drain_map_actions():
                    self._broadcast(
                        {
                            "type": "map_action",
                            **action,
                        }
                    )

            except Exception as e:
                self._broadcast(
                    {
                        "type":
                            "error",
                        "text":
                            f"Jarvis hit an error: {e}",
                    }
                )

            finally:
                self._broadcast(
                    {
                        "type":
                            "reply_done",
                    }
                )

    def _tool_name_from_step(
        self,
        message,
    ):
        body = (
            message[len("Step: "):]
            if message.startswith(
                "Step: "
            )
            else message
        )

        return body.split(
            "("
        )[0].strip()

    def broadcast_tool_step(
        self,
        message,
    ):
        if message.startswith(
            "Plan:"
        ):
            self._broadcast(
                {
                    "type":
                        "plan",
                    "text":
                        message[
                            len("Plan:"):
                        ].strip(),
                }
            )

            return

        name = (
            self._tool_name_from_step(
                message
            )
        )

        self.set_state(
            "tool",
            {
                "name":
                    name
            },
        )

        self._broadcast(
            {
                "type":
                    "tool_step",
                "text":
                    message,
            }
        )

    def broadcast_reply_chunk(
        self,
        sentence,
    ):
        self.set_state(
            "speaking"
        )

        self._broadcast(
            {
                "type":
                    "reply_chunk",
                "text":
                    sentence,
            }
        )

    # -- Confirmation ---------------------------------------------------

    def request_confirmation(
        self,
        name,
        arguments,
    ):
        if (
            not self._available
            or not self._authenticated_clients()
        ):
            print(
                f"[Jarvis HUD] No authenticated HUD "
                f"client connected to confirm "
                f"'{name}' -- declining."
            )

            return False

        request_id = str(
            uuid.uuid4()
        )

        event = threading.Event()

        with self._pending_confirms_lock:
            self._pending_confirms[
                request_id
            ] = {
                "event":
                    event,
                "approved":
                    None,
            }

        self._broadcast(
            {
                "type":
                    "confirm_request",
                "id":
                    request_id,
                "tool":
                    name,
                "args":
                    arguments,
            }
        )

        answered = event.wait(
            timeout=
                CONFIRM_TIMEOUT_SECONDS
        )

        with self._pending_confirms_lock:
            pending = (
                self._pending_confirms.pop(
                    request_id,
                    None,
                )
            )

        if (
            not answered
            or pending is None
        ):
            print(
                f"[Jarvis HUD] Confirmation "
                f"for '{name}' timed out "
                f"-- declining."
            )

            return False

        return bool(
            pending["approved"]
        )

    # -- Sending ---------------------------------------------------------

    async def _send_json(
        self,
        websocket,
        payload,
    ):
        try:
            await websocket.send(
                json.dumps(payload)
            )

            return True

        except Exception:
            self._clients.discard(
                websocket
            )

            return False

    def _send_to_socket(
        self,
        websocket,
        payload,
    ):
        if (
            not self._available
            or self._loop is None
        ):
            return False

        try:
            future = (
                asyncio.run_coroutine_threadsafe(
                    self._send_json(
                        websocket,
                        payload,
                    ),
                    self._loop,
                )
            )

            future.result(
                timeout=2
            )

            return True

        except Exception:
            return False

    def _close_socket(
        self,
        websocket,
    ):
        if self._loop is None:
            return

        async def close():
            try:
                await websocket.close()
            except Exception:
                pass

        try:
            asyncio.run_coroutine_threadsafe(
                close(),
                self._loop,
            )
        except Exception:
            pass

    async def _broadcast_json(
        self,
        payload,
    ):
        if not self._devices:
            return

        message = json.dumps(
            payload
        )

        for websocket in list(
            self._devices.keys()
        ):
            try:
                await websocket.send(
                    message
                )

            except Exception:
                self._unregister_client(
                    websocket
                )

                self._clients.discard(
                    websocket
                )

    def _broadcast(
        self,
        payload,
    ):
        if (
            not self._available
            or self._loop is None
        ):
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_json(
                    payload
                ),
                self._loop,
            )

        except Exception:
            pass

    def set_state(
        self,
        state,
        meta=None,
    ):
        self._broadcast(
            {
                "type":
                    "state",
                "state":
                    state,
                "meta":
                    meta or {},
            }
        )


hud = HUDBridge()
