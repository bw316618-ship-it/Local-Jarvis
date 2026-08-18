"""Step 13 backend smoke tests."""

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
