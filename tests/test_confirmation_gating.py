"""Confirmation gating: risky tools must be approved before executing;
declined ones must never run; safe tools must never be asked about."""

from brain.llm import JarvisLLM
from tools.tools import TOOL_FUNCTIONS


def make_jarvis(confirm_callback):
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = confirm_callback
    return jarvis


def test_declined_risky_tool_never_executes(monkeypatch):
    executed = []
    monkeypatch.setitem(TOOL_FUNCTIONS, "run_command", lambda command: executed.append(command) or "ran")

    jarvis = make_jarvis(confirm_callback=lambda name, args: False)
    result = jarvis._run_tool_call({"function": {"name": "run_command", "arguments": {"command": "rm -rf /"}}})

    assert executed == [], "declined risky tool must never actually run"
    assert "declined" in result.lower()


def test_approved_risky_tool_executes(monkeypatch):
    executed = []
    monkeypatch.setitem(TOOL_FUNCTIONS, "run_command", lambda command: executed.append(command) or "ran")

    jarvis = make_jarvis(confirm_callback=lambda name, args: True)
    result = jarvis._run_tool_call({"function": {"name": "run_command", "arguments": {"command": "echo hi"}}})

    assert executed == ["echo hi"]
    assert result == "ran"


def test_safe_tool_never_asks_for_confirmation(monkeypatch):
    confirm_calls = []
    monkeypatch.setitem(TOOL_FUNCTIONS, "calculate", lambda expression: "42")

    jarvis = make_jarvis(confirm_callback=lambda name, args: confirm_calls.append((name, args)) or True)
    result = jarvis._run_tool_call({"function": {"name": "calculate", "arguments": {"expression": "6*7"}}})

    assert confirm_calls == [], "safe tools must never trigger a confirmation prompt"
    assert result == "42"


def test_unknown_tool_returns_error_without_crashing():
    jarvis = make_jarvis(confirm_callback=lambda name, args: True)
    result = jarvis._run_tool_call({"function": {"name": "not_a_real_tool", "arguments": {}}})
    assert "unknown tool" in result.lower()


def test_tool_exception_is_caught_and_reported(monkeypatch):
    def _boom(**kwargs):
        raise ValueError("something broke")

    monkeypatch.setitem(TOOL_FUNCTIONS, "calculate", _boom)
    jarvis = make_jarvis(confirm_callback=lambda name, args: True)
    result = jarvis._run_tool_call({"function": {"name": "calculate", "arguments": {"expression": "1+1"}}})

    assert "error" in result.lower()
    assert "something broke" in result
