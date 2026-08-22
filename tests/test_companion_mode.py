"""Companion mode tests."""

from unittest.mock import MagicMock
import pytest

import brain.llm as llm_module
from brain.llm import JarvisLLM
from brain.mode_config import COMPANION_PROMPT
from voice import session_state
from tools.session_control import enter_companion_mode, exit_companion_mode, SESSION_TOOL_FUNCTIONS, SESSION_RISKY_TOOLS


@pytest.fixture(autouse=True)
def reset_companion_flag():
    session_state.exit_companion_mode()
    yield
    session_state.exit_companion_mode()


def _stream(content, tool_calls=None):
    return iter([{"message": {"content": content, "tool_calls": tool_calls}}])


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK-MODE-PROMPT"
    jarvis.companion_system_prompt = COMPANION_PROMPT
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock(search=lambda q, **kwargs: [])
    jarvis.short_term = []
    return jarvis


def test_flag_starts_clear_and_toggles():
    assert not session_state.is_companion_mode()
    session_state.enter_companion_mode()
    assert session_state.is_companion_mode()
    session_state.exit_companion_mode()
    assert not session_state.is_companion_mode()


def test_toggle_companion_mode_flips_and_returns_new_state():
    assert session_state.toggle_companion_mode() is True
    assert session_state.toggle_companion_mode() is False


def test_registered_and_not_risky():
    assert "enter_companion_mode" in SESSION_TOOL_FUNCTIONS
    assert "exit_companion_mode" in SESSION_TOOL_FUNCTIONS
    assert "enter_companion_mode" not in SESSION_RISKY_TOOLS
    assert "exit_companion_mode" not in SESSION_RISKY_TOOLS


def test_tool_functions_flip_the_same_flag_the_model_can_call():
    enter_companion_mode()
    assert session_state.is_companion_mode()
    exit_companion_mode()
    assert not session_state.is_companion_mode()


def test_chat_uses_task_prompt_and_full_tools_by_default(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append((messages[0]["content"], tools)) or _stream("42")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    jarvis.chat("what is 6*7", on_step=lambda m: None)
    assert captured[0][0] == "TASK-MODE-PROMPT"
    # Relevance filtering (brain/tool_relevance.py) now narrows NORMAL
    # mode's offered tools per turn for non-trivial messages, so this can
    # no longer assert exact identity with the full TOOL_SCHEMAS list --
    # what actually matters is that nothing foreign leaked in and that
    # session-control tools are always reachable regardless of ranking.
    result_names = {t["function"]["name"] for t in captured[0][1]}
    full_names = {t["function"]["name"] for t in llm_module.TOOL_SCHEMAS}
    assert result_names <= full_names
    assert "mute_jarvis" in result_names


def test_chat_uses_companion_prompt_and_limited_tools_when_flag_set(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append((messages[0]["content"], tools)) or _stream("Sure, tell me more.")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.enter_companion_mode()
    jarvis.chat("I just want to talk something through", on_step=lambda m: None)
    assert captured[0][0] == COMPANION_PROMPT
    assert captured[0][1] is llm_module.SESSION_TOOL_SCHEMAS


def test_chat_skips_planning_in_companion_mode_even_for_multi_clause_input(monkeypatch):
    jarvis = make_jarvis()
    plan_calls = []
    monkeypatch.setattr(JarvisLLM, "_make_plan", lambda self, msg: plan_calls.append(msg) or "should not run")
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda *a, **k: _stream("Okay, go on.")
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.enter_companion_mode()
    jarvis.chat("first I was worried about the deadline, and then my mind went somewhere else", on_step=lambda m: None)
    assert plan_calls == []


def test_model_can_exit_companion_mode_via_the_tool_mid_conversation(monkeypatch):
    jarvis = make_jarvis()
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda *a, **k: _stream("noted")
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.enter_companion_mode()
    jarvis.chat("talking mode", on_step=lambda m: None)
    exit_companion_mode()
    captured = []
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append(tools) or _stream("back to it")
    )
    jarvis.chat("back to work", on_step=lambda m: None)
    result_names = {t["function"]["name"] for t in captured[0]}
    full_names = {t["function"]["name"] for t in llm_module.TOOL_SCHEMAS}
    assert result_names <= full_names
    assert "mute_jarvis" in result_names


def test_companion_user_message_is_not_framed_as_a_question(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append(messages) or _stream("That makes sense.")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.enter_companion_mode()
    jarvis.chat("That was the part I missed most.", on_step=lambda m: None)
    user_message = captured[0][-1]["content"]
    assert "User:\nThat was the part I missed most." in user_message
    assert "Question:\n" not in user_message


def test_companion_tools_are_resolved_from_session_registry(monkeypatch):
    jarvis = make_jarvis()
    session_state.enter_companion_mode()
    result = jarvis._run_tool_call({"function": {"name": "exit_companion_mode", "arguments": {}}})
    assert "Back to normal mode" in result
    assert not session_state.is_companion_mode()


def test_companion_prompt_explicitly_prevents_repeated_questions():
    assert "Do not ask the same question again in different words." in COMPANION_PROMPT
    assert "A response does not need to contain a question." in COMPANION_PROMPT
    assert "If they make a statement, respond to the statement." in COMPANION_PROMPT
    assert "Never ask a question merely to keep the conversation alive." in COMPANION_PROMPT
