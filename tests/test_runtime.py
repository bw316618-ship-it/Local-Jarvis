"""Step 12 smoke tests for the Jarvis runtime boundary."""

from brain.runtime import JarvisRuntime


def test_runtime_imports():
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    assert runtime is not None
