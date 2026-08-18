"""
Jarvis Backend — Step 14.1
Persistent authenticated backend with live LAN device pairing.

This fixes the Step 14 phone loop:

- Untrusted devices remain connected while waiting for approval.
- Trusted devices receive a `device_access_request`.
- The trusted HUD answers with `device_approval`.
- Approval creates and persists a token.
- The token is sent once to the waiting device.
- The waiting device becomes authenticated on the SAME WebSocket.
- The authenticated device can immediately use Jarvis.
- Future connections authenticate with the stored token.

Compatible with the current hud.js protocol:
    device_access_request
    device_approval
    auth_pending
    auth_denied
    auth_granted
"""

import asyncio
import json
import threading
import uuid
from pathlib import Path

import websockets

from brain.runtime import JarvisRuntime
from config import CONFIG
from security.devices import DeviceAuth, default_auth_path


ROOT = Path(__file__).resolve().parent
BACKEND_WS_PORT = CONFIG["backend_ws_port"]


class JarvisBackend:
    def __init__(self, runtime=None, ws_port=BACKEND_WS_PORT):
        # `runtime`, if given, is only used as the very first device's
        # JarvisRuntime (see _get_runtime) -- kept so tests/callers can
        # still inject a mock. Every device gets its OWN JarvisRuntime
        # (and therefore its own JarvisLLM / short-term history / risky-
        # tool confirmation routing) so that two devices talking to Jarvis
        # at the same time never share conversation state or cross-route
        # a confirmation prompt to the wrong device.
        self.runtime = runtime or JarvisRuntime()
        self.ws_port = ws_port

        self.auth = DeviceAuth(
            default_auth_path(ROOT)
        )

        self._loop = None
        self._stop_event = None
        self._clients = set()

        # websocket -> trusted device record
        self._authenticated = {}

        # request_id -> {
        #   request: {...},
        #   websocket: websocket,
        #   event: asyncio.Event,
        #   approved: bool | None,
        #   token: str | None,
        # }
        self._pending = {}

        # device_id -> JarvisRuntime, and device_id -> a lock serializing
        # that device's own messages. Keyed by device_id (not websocket)
        # so a device that reconnects on a new socket keeps its running
        # conversation rather than starting a fresh one.
        self._runtimes = {}
        self._runtime_locks = {}

        self._lock = threading.RLock()
        self._available = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._available:
            return True

        thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="jarvis-backend",
        )
        thread.start()

        self._available = True
        return True

    def stop(self):
        if not self._available:
            return

        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(
                self._stop_event.set
            )

        self._available = False

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(
                self._serve()
            )
        finally:
            self._loop.close()
            self._loop = None

    async def _serve(self):
        self._stop_event = asyncio.Event()

        async with websockets.serve(
            self._handle_client,
            "0.0.0.0",
            self.ws_port,
        ):
            print(
                f"[Jarvis Backend] WebSocket listening "
                f"on 0.0.0.0:{self.ws_port}"
            )

            await self._stop_event.wait()

    # ------------------------------------------------------------------
    # Connection / authentication
    # ------------------------------------------------------------------

    async def _handle_client(self, websocket):
        self._clients.add(websocket)

        try:
            raw = await asyncio.wait_for(
                websocket.recv(),
                timeout=15,
            )

            try:
                data = json.loads(raw)
            except Exception:
                await self._send(
                    websocket,
                    {
                        "type": "auth_error",
                        "text": "Invalid authentication payload.",
                    },
                )
                return

            if data.get("type") != "authenticate":
                await self._send(
                    websocket,
                    {
                        "type": "auth_error",
                        "text": "Authentication is required.",
                    },
                )
                return

            device = {
                "device_id": str(
                    data.get("device_id") or ""
                ).strip(),
                "device_type": str(
                    data.get("device_type") or "unknown"
                ).strip().lower(),
                "name": str(
                    data.get("name") or "Unknown device"
                ).strip(),
            }

            token = str(
                data.get("token") or ""
            )

            if not device["device_id"]:
                await self._send(
                    websocket,
                    {
                        "type": "auth_error",
                        "text": "Missing device ID.",
                    },
                )
                return

            if device["device_type"] not in {
                "pc",
                "phone",
            }:
                device["device_type"] = "unknown"

            # ----------------------------------------------------------
            # Existing trusted device
            # ----------------------------------------------------------

            trusted = self.auth.authenticate(
                device["device_id"],
                token,
            )

            if trusted is not None:
                await self._mark_authenticated(
                    websocket,
                    trusted,
                )

                await self._authenticated_loop(
                    websocket
                )

                return

            # ----------------------------------------------------------
            # Unknown device: keep connection open for pairing.
            # ----------------------------------------------------------

            request_id = str(uuid.uuid4())

            request = self.auth.request_pairing(
                device["device_id"],
                device["device_type"],
                device["name"],
            )

            event = asyncio.Event()

            pending = {
                "request": request,
                "websocket": websocket,
                "event": event,
                "approved": None,
                "token": None,
            }

            with self._lock:
                self._pending[request_id] = pending

            await self._send(
                websocket,
                {
                    "type": "auth_pending",
                    "request_id": request_id,
                    "text": (
                        "Waiting for approval from a trusted "
                        "Jarvis device."
                    ),
                },
            )

            await self._broadcast_to_authenticated(
                {
                    "type": "device_access_request",
                    "request_id": request_id,
                    "device": device,
                }
            )

            # IMPORTANT:
            # Do NOT close or return here.
            # The phone must remain on this WebSocket until the PC
            # approves or denies it.
            try:
                await asyncio.wait_for(
                    event.wait(),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                with self._lock:
                    self._pending.pop(
                        request_id,
                        None,
                    )

                await self._send(
                    websocket,
                    {
                        "type": "auth_denied",
                        "text": (
                            "Device pairing timed out."
                        ),
                    },
                )
                return

            with self._lock:
                result = self._pending.pop(
                    request_id,
                    None,
                )

            if result is None:
                return

            # ----------------------------------------------------------
            # Denied
            # ----------------------------------------------------------

            if not result["approved"]:
                await self._send(
                    websocket,
                    {
                        "type": "auth_denied",
                        "text": "Device access was denied.",
                    },
                )
                return

            # ----------------------------------------------------------
            # Approved
            # ----------------------------------------------------------

            token = result["token"]

            if not token:
                await self._send(
                    websocket,
                    {
                        "type": "auth_error",
                        "text": "Pairing failed: no credential was generated.",
                    },
                )
                return

            trusted = self.auth.authenticate(
                device["device_id"],
                token,
            )

            if trusted is None:
                await self._send(
                    websocket,
                    {
                        "type": "auth_error",
                        "text": "Pairing failed: credential verification failed.",
                    },
                )
                return

            await self._mark_authenticated(
                websocket,
                trusted,
                token=token,
            )

            # The same WebSocket stays alive. No reconnect is required.
            await self._authenticated_loop(
                websocket
            )

        except websockets.exceptions.ConnectionClosed:
            pass

        except asyncio.TimeoutError:
            pass

        except Exception as exc:
            print(
                f"[Jarvis Backend] Client error: {exc}"
            )

        finally:
            self._remove_client(
                websocket
            )

    async def _mark_authenticated(
        self,
        websocket,
        device,
        token=None,
    ):
        with self._lock:
            self._authenticated[
                websocket
            ] = dict(device)

        payload = {
            "type": "auth_granted",
            "device": {
                "device_id": device["device_id"],
                "device_type": device["device_type"],
                "name": device["name"],
            },
        }

        # Only include the raw token during the initial pairing.
        if token:
            payload["token"] = token
            payload["bootstrap"] = False

        await self._send(
            websocket,
            payload,
        )

        await self._send_registry(
            websocket
        )

        await self._broadcast_registry()

        print(
            "[Jarvis Auth] Device authenticated:",
            device["name"],
            device["device_type"],
            device["device_id"],
        )

    # ------------------------------------------------------------------
    # Authenticated message loop
    # ------------------------------------------------------------------

    async def _authenticated_loop(
        self,
        websocket,
    ):
        async for raw in websocket:
            await self._handle_message(
                websocket,
                raw,
            )

    async def _handle_message(
        self,
        websocket,
        raw,
    ):
        with self._lock:
            device = self._authenticated.get(
                websocket
            )

        if device is None:
            return

        try:
            data = json.loads(raw)
        except Exception:
            return

        msg_type = data.get("type")

        # --------------------------------------------------------------
        # Pairing approval
        # --------------------------------------------------------------

        if msg_type in {
            "device_approval",
            "approve_pairing",
        }:
            await self._approve_pairing(
                websocket,
                data.get("request_id"),
                bool(data.get("approved", False)),
            )
            return

        # --------------------------------------------------------------
        # Device revocation
        # --------------------------------------------------------------

        if msg_type == "revoke_device":
            await self._revoke_device(
                websocket,
                str(
                    data.get("device_id") or ""
                ),
            )
            return

        # --------------------------------------------------------------
        # Jarvis chat
        # --------------------------------------------------------------

        if msg_type == "user_message":
            text = (
                data.get("text") or ""
            ).strip()

            if not text:
                return

            threading.Thread(
                target=self._process_message,
                args=(text, websocket),
                daemon=True,
            ).start()

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    async def _approve_pairing(
        self,
        approver_socket,
        request_id,
        approved,
    ):
        with self._lock:
            approver = self._authenticated.get(
                approver_socket
            )

            pending = self._pending.get(
                request_id
            )

        # Only an authenticated device can approve.
        if approver is None or pending is None:
            return

        if not approved:
            pending["approved"] = False
            pending["token"] = None
            pending["event"].set()

            print(
                "[Jarvis Auth] Pairing denied:",
                pending["request"]["name"],
            )
            return

        request = pending["request"]

        try:
            token = self.auth.approve_pending(
                request
            )
        except ValueError:
            pending["approved"] = False
            pending["token"] = None
            pending["event"].set()
            return

        pending["approved"] = True
        pending["token"] = token
        pending["event"].set()

        print(
            "[Jarvis Auth] Pairing approved:",
            request["name"],
            request["device_type"],
        )

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    async def _revoke_device(
        self,
        approver_socket,
        device_id,
    ):
        with self._lock:
            approver = self._authenticated.get(
                approver_socket
            )

        if approver is None or not device_id:
            return

        # Prevent a device from revoking itself.
        if device_id == approver["device_id"]:
            return

        if not self.auth.revoke(device_id):
            return

        target = None

        with self._lock:
            for websocket, device in list(
                self._authenticated.items()
            ):
                if device["device_id"] == device_id:
                    target = websocket
                    del self._authenticated[
                        websocket
                    ]
                    break

        if target is not None:
            await self._send(
                target,
                {
                    "type": "device_revoked",
                    "device_id": device_id,
                    "text": (
                        "This device has been revoked."
                    ),
                },
            )

            try:
                await target.close()
            except Exception:
                pass

        await self._broadcast_registry()

    # ------------------------------------------------------------------
    # Jarvis runtime
    # ------------------------------------------------------------------

    def _get_runtime(self, device_id):
        """Return the (JarvisRuntime, Lock) pair for a device, creating
        them on first contact. The lock serializes that ONE device's own
        messages (so a device firing off two quick messages doesn't race
        itself); it does not block other devices, who each have their
        own runtime and lock.
        """
        key = device_id or "__unknown__"

        with self._lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                # Reuse the constructor-provided/default runtime for the
                # first device only (keeps `JarvisBackend(runtime=...)`
                # dependency injection working for tests); every device
                # after that gets a brand-new, fully isolated runtime.
                runtime = self.runtime if not self._runtimes else JarvisRuntime()
                self._runtimes[key] = runtime
                self._runtime_locks[key] = threading.Lock()

            return runtime, self._runtime_locks[key]

    def _process_message(
        self,
        text,
        websocket,
    ):
        if not self._loop:
            return

        with self._lock:
            device = self._authenticated.get(websocket)
        device_id = device["device_id"] if device else None

        runtime, runtime_lock = self._get_runtime(device_id)

        # Held for the duration of this device's turn (including the
        # blocking future.result() below) so a second fast message from
        # the SAME device queues up rather than racing this one for
        # runtime.jarvis.confirm_callback / short_term history.
        with runtime_lock:
            future = asyncio.run_coroutine_threadsafe(
                self._process_message_async(
                    text,
                    websocket,
                    runtime,
                ),
                self._loop,
            )

            try:
                future.result()
            except Exception:
                pass

    async def _process_message_async(
        self,
        text,
        websocket,
        runtime,
    ):
        adapter = BackendSurface(
            self,
            websocket,
        )

        try:
            runtime.handle_message(
                text,
                hud=adapter,
            )

        except Exception as exc:
            await self._send(
                websocket,
                {
                    "type": "error",
                    "text": str(exc),
                },
            )

        finally:
            await self._send(
                websocket,
                {
                    "type": "reply_done",
                },
            )

    # ------------------------------------------------------------------
    # Device registry
    # ------------------------------------------------------------------

    async def _send_registry(
        self,
        websocket,
    ):
        await self._send(
            websocket,
            {
                "type": "device_registry",
                "devices": self._connected_devices(),
            },
        )

    async def _broadcast_registry(self):
        await self._broadcast_to_authenticated(
            {
                "type": "device_registry",
                "devices": self._connected_devices(),
            }
        )

    def _connected_devices(self):
        with self._lock:
            return [
                {
                    "device_id": device["device_id"],
                    "device_type": device["device_type"],
                    "name": device["name"],
                }
                for device in self._authenticated.values()
            ]

    async def _broadcast_to_authenticated(
        self,
        payload,
    ):
        with self._lock:
            clients = list(
                self._authenticated.keys()
            )

        for websocket in clients:
            await self._send(
                websocket,
                payload,
            )

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    async def _send(
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
            return False

    def _send_from_thread(
        self,
        websocket,
        payload,
    ):
        if not self._loop:
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._send(
                    websocket,
                    payload,
                ),
                self._loop,
            )
        except Exception:
            pass

    def _remove_client(
        self,
        websocket,
    ):
        self._clients.discard(websocket)

        with self._lock:
            self._authenticated.pop(
                websocket,
                None,
            )

            for request_id, pending in list(
                self._pending.items()
            ):
                if pending["websocket"] is websocket:
                    self._pending.pop(
                        request_id,
                        None,
                    )

        if self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._broadcast_registry(),
                    self._loop,
                )
            except Exception:
                pass


class BackendSurface:
    """Adapter used by JarvisRuntime for this authenticated client."""

    def __init__(
        self,
        backend,
        websocket,
    ):
        self.backend = backend
        self.websocket = websocket

    def set_state(
        self,
        state,
        meta=None,
    ):
        self.backend._send_from_thread(
            self.websocket,
            {
                "type": "state",
                "state": state,
                "meta": meta or {},
            },
        )

    def broadcast_reply_chunk(
        self,
        sentence,
    ):
        self.set_state(
            "speaking"
        )

        self.backend._send_from_thread(
            self.websocket,
            {
                "type": "reply_chunk",
                "text": sentence,
            },
        )

    def broadcast_tool_step(
        self,
        message,
    ):
        self.set_state(
            "tool",
            {
                "name":
                    self._tool_name(message),
            },
        )

        self.backend._send_from_thread(
            self.websocket,
            {
                "type": "tool_step",
                "text": message,
            },
        )

    def request_confirmation(
        self,
        name,
        arguments,
    ):
        # Keep the security boundary fail-closed until remote confirmation
        # routing is implemented separately.
        return False

    @staticmethod
    def _tool_name(message):
        body = (
            message[len("Step: "):]
            if message.startswith("Step: ")
            else message
        )

        return body.split("(")[0].strip()


backend = JarvisBackend()
