"""Companion mode: voice/session_state.py's flag, tools/session_control.py's
toggle tools, and brain/llm.py's chat() actually honoring the flag by
swapping the system prompt and tool list, and skipping planning.
"""

from unittest.mock import MagicMock

import pytest

import brain.llm as llm_module
from brain.llm import JarvisLLM
from voice import session_state
from tools.session_control import (
    enter_companion_mode,
    exit_companion_mode,
    SESSION_TOOL_FUNCTIONS,
    SESSION_RISKY_TOOLS,
)


@pytest.fixture(autouse=True)
def reset_companion_flag():
    """Module-level Event -- make sure one test's toggle can't leak into
    the next, the same way conftest.py resets audit_log/transcript paths."""
    session_state.exit_companion_mode()
    yield
    session_state.exit_companion_mode()


def _stream(content, tool_calls=None):
    return iter([{"message": {"content": content, "tool_calls": tool_calls}}])


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK-MODE-PROMPT"
    jarvis.companion_system_prompt = "COMPANION-MODE-PROMPT"
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock(search=lambda q, **kwargs: [])
    jarvis.short_term = []
    return jarvis


# --- session_state ----------------------------------------------------

def test_flag_starts_clear_and_toggles():
    assert session_state.is_companion_mode() is False
    session_state.enter_companion_mode()
    assert session_state.is_companion_mode() is True
    session_state.exit_companion_mode()
    assert session_state.is_companion_mode() is False


def test_toggle_companion_mode_flips_and_returns_new_state():
    assert session_state.toggle_companion_mode() is True
    assert session_state.is_companion_mode() is True
    assert session_state.toggle_companion_mode() is False
    assert session_state.is_companion_mode() is False


# --- tools/session_control.py ------------------------------------------

def test_registered_and_not_risky():
    """Same bar as mute/unmute: a trivially reversible local-state
    toggle, not a confirmation-gated action."""
    assert "enter_companion_mode" in SESSION_TOOL_FUNCTIONS
    assert "exit_companion_mode" in SESSION_TOOL_FUNCTIONS
    assert "enter_companion_mode" not in SESSION_RISKY_TOOLS
    assert "exit_companion_mode" not in SESSION_RISKY_TOOLS


def test_tool_functions_flip_the_same_flag_the_model_can_call():
    enter_companion_mode()
    assert session_state.is_companion_mode() is True
    exit_companion_mode()
    assert session_state.is_companion_mode() is False


# --- brain/llm.py chat() -------------------------------------------------

def test_chat_uses_task_prompt_and_full_tools_by_default(monkeypatch):
    jarvis = make_jarvis()
    captured = []

    def fake_chat(model, messages, tools=None, stream=False, **kwargs):
        captured.append((messages[0]["content"], tools))
        return _stream("42", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

    jarvis.chat("what is 6*7", on_step=lambda m: None)

    system_prompt_used, tools_used = captured[0]
    assert system_prompt_used == "TASK-MODE-PROMPT"
    assert tools_used is llm_module.TOOL_SCHEMAS


def test_chat_uses_companion_prompt_and_limited_tools_when_flag_set(monkeypatch):
    jarvis = make_jarvis()
    captured = []

    def fake_chat(model, messages, tools=None, stream=False, **kwargs):
        captured.append((messages[0]["content"], tools))
        return _stream("Sure, tell me more.", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

    session_state.enter_companion_mode()
    jarvis.chat("I just want to talk something through", on_step=lambda m: None)

    system_prompt_used, tools_used = captured[0]
    assert system_prompt_used == "COMPANION-MODE-PROMPT"
    assert tools_used is llm_module.SESSION_TOOL_SCHEMAS
    # The full task registry should not be reachable in this mode.
    assert tools_used is not llm_module.TOOL_SCHEMAS


def test_chat_skips_planning_in_companion_mode_even_for_multi_clause_input(monkeypatch):
    """A message with 'and then'/commas would normally trigger the
    planning round (see _looks_like_multi_step) -- companion mode should
    bypass that entirely regardless of phrasing."""
    jarvis = make_jarvis()
    plan_calls = []

    monkeypatch.setattr(
        JarvisLLM, "_make_plan", lambda self, msg: plan_calls.append(msg) or "should not run"
    )

    def fake_chat(model, messages, tools=None, stream=False, **kwargs):
        return _stream("Okay, go on.", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

    session_state.enter_companion_mode()
    steps = []
    jarvis.chat(
        "first I was worried about the deadline, and then my mind went "
        "somewhere else entirely, honestly",
        on_step=steps.append,
    )

    assert plan_calls == [], "companion mode must never trigger the task-planning round"
    assert steps == []


def test_model_can_exit_companion_mode_via_the_tool_mid_conversation(monkeypatch):
    """Regression guard: the flag must be read fresh at the top of every
    chat() call, not cached on the instance, so a mid-conversation
    exit_companion_mode() tool call takes effect on the very next turn."""
    jarvis = make_jarvis()

    def fake_chat(model, messages, tools=None, stream=False, **kwargs):
        return _stream("noted", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])

    session_state.enter_companion_mode()
    jarvis.chat("talking mode", on_step=lambda m: None)
    assert session_state.is_companion_mode() is True

    exit_companion_mode()  # simulates the model calling the tool

    captured = []
    fake_client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append(tools) or _stream("back to it", None)
    )
    jarvis.chat("ok let's get back to work", on_step=lambda m: None)

    assert captured[0] is llm_module.TOOL_SCHEMAS
