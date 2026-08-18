"""Step 13 backend smoke tests."""

from backend import JarvisBackend


def test_backend_constructs():
    backend = JarvisBackend()
    assert backend.ws_port > 0
    assert backend.runtime is not None
