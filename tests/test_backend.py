
import asyncio
import json
from unittest.mock import MagicMock

from backend import JarvisBackend
from brain.runtime import JarvisRuntime


def test_backend_constructs():
    backend = JarvisBackend()
    assert backend.ws_port > 0
    assert backend.runtime is not None


def test_different_devices_get_isolated_runtimes():
    """Regression test: JarvisBackend used to hand every connected device
    the SAME JarvisRuntime (and therefore the same JarvisLLM -- same
    short_term conversation history, same confirm_callback). Two devices
    talking to Jarvis around the same time would bleed context into each
    other and could route one device's risky-tool confirmation prompt to
    a completely different device. Each device_id must now get its own
    runtime."""
    backend = JarvisBackend(runtime=MagicMock())

    runtime_a, lock_a = backend._get_runtime("device-a")
    runtime_b, lock_b = backend._get_runtime("device-b")

    assert runtime_a is not runtime_b
    assert lock_a is not lock_b


def test_same_device_reuses_its_runtime_across_calls():
    """A device's conversation should survive it sending a second message
    (or reconnecting on a new socket) -- it must always get back the SAME
    JarvisRuntime it had before, not a fresh one that's lost context."""
    backend = JarvisBackend(runtime=MagicMock())

    runtime_first, lock_first = backend._get_runtime("device-a")
    runtime_second, lock_second = backend._get_runtime("device-a")

    assert runtime_first is runtime_second
    assert lock_first is lock_second


def test_first_device_reuses_the_injected_runtime():
    """JarvisBackend(runtime=...) is how tests/callers inject a mock or
    pre-built runtime -- the first device to make contact should get
    exactly that instance, not a silently-substituted new one."""
    injected = MagicMock()
    backend = JarvisBackend(runtime=injected)

    runtime, _ = backend._get_runtime("device-a")

    assert runtime is injected


def test_unauthenticated_device_id_still_gets_a_real_runtime():
    """_get_runtime must not blow up if called with device_id=None (e.g.
    a message arriving before the device lookup resolves)."""
    backend = JarvisBackend(runtime=MagicMock())

    runtime, lock = backend._get_runtime(None)

    assert isinstance(runtime, JarvisRuntime) or runtime is backend.runtime
    assert lock is not None


class _FakeWebSocket:
    """Minimal stand-in for a websockets connection: feeds `_handle_client`
    one incoming authenticate message, then (once authenticated) never
    yields another message, so the async-for in _authenticated_loop just
    ends the coroutine naturally instead of hanging."""

    def __init__(self, first_message):
        self._to_recv = [json.dumps(first_message)]
        self.sent = []

    async def recv(self):
        if self._to_recv:
            return self._to_recv.pop(0)
        raise StopAsyncIteration

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_first_device_on_a_fresh_install_is_auto_bootstrapped(tmp_path):
    """Regression test: on a fresh install (empty trusted_devices.json)
    the HUD is normally the very first thing to connect. The old code
    treated it as an unknown device and made it wait for approval from
    an ALREADY-trusted device -- but none can exist yet, so it would
    always time out and never reach _authenticated_loop(), meaning it
    never received a single "state" (thinking/idle/speaking/...) message.
    bootstrap_device() must now be used to trust the first device
    immediately instead of making it wait for an approver that can never
    exist."""
    from security.devices import DeviceAuth

    backend = JarvisBackend(runtime=MagicMock())
    backend.auth = DeviceAuth(tmp_path / "trusted_devices.json")

    ws = _FakeWebSocket({
        "type": "authenticate",
        "device_id": "jarvis-hud-test",
        "device_type": "pc",
        "name": "Test HUD",
        "token": "",
    })

    asyncio.run(backend._handle_client(ws))

    kinds = [msg["type"] for msg in ws.sent]
    assert "auth_granted" in kinds, (
        f"first device on a fresh install should be auto-bootstrapped "
        f"and authenticated, not left pending; got message types: {kinds}"
    )
    assert "auth_pending" not in kinds
    assert "auth_denied" not in kinds

    granted = next(m for m in ws.sent if m["type"] == "auth_granted")
    assert granted["bootstrap"] is True
    assert granted["token"]

    # The device really is trusted now, not just told so.
    assert backend.auth.is_trusted("jarvis-hud-test")


def test_second_device_on_a_nonempty_install_still_needs_approval(tmp_path):
    """The bootstrap path must only fire when NO trusted device exists
    yet. Once there's at least one trusted device, a second unknown
    device must still go through normal pairing (wait for approval),
    not get auto-trusted too -- otherwise anyone on the LAN could add
    themselves as a trusted device with no approval at all."""
    from security.devices import DeviceAuth

    backend = JarvisBackend(runtime=MagicMock())
    backend.auth = DeviceAuth(tmp_path / "trusted_devices.json")

    # Seed one already-trusted device, simulating a install that's past
    # its first-ever connection.
    backend.auth.bootstrap_device("jarvis-pc-existing", "pc", "Existing PC")

    ws = _FakeWebSocket({
        "type": "authenticate",
        "device_id": "jarvis-phone-new",
        "device_type": "phone",
        "name": "New Phone",
        "token": "",
    })

    # No other device is connected/authenticated to approve it, so this
    # should time out rather than hang forever -- shrink the wait so the
    # test doesn't take 120s.
    import backend as backend_module
    original_wait_for = asyncio.wait_for

    async def fast_wait_for(awaitable, timeout):
        if timeout == 120:
            timeout = 0.05
        return await original_wait_for(awaitable, timeout)

    backend_module.asyncio.wait_for = fast_wait_for
    try:
        asyncio.run(backend._handle_client(ws))
    finally:
        backend_module.asyncio.wait_for = original_wait_for

    kinds = [msg["type"] for msg in ws.sent]
    assert "auth_pending" in kinds
    assert "auth_granted" not in kinds
    assert not backend.auth.is_trusted("jarvis-phone-new")
