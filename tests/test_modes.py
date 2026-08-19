"""Tests for generalized Jarvis modes and their tool boundaries."""

from unittest.mock import MagicMock
import pytest

import brain.llm as llm_module
from brain.llm import JarvisLLM
from brain.mode_config import NORMAL, COMPANION, CREATIVE, COMPANION_PROMPT
from voice import session_state
from voice import document_state


@pytest.fixture(autouse=True)
def reset_mode_and_document():
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()
    yield
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()


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


def test_mode_starts_normal():
    assert session_state.current_mode() == NORMAL


def test_named_modes_switch():
    session_state.set_mode(COMPANION)
    assert session_state.current_mode() == COMPANION
    session_state.set_mode(CREATIVE)
    assert session_state.current_mode() == CREATIVE
    session_state.set_mode(NORMAL)
    assert session_state.current_mode() == NORMAL


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        session_state.set_mode("not-a-real-mode")


def test_companion_compatibility_helpers_still_work():
    session_state.enter_companion_mode()
    assert session_state.is_companion_mode()
    session_state.exit_companion_mode()
    assert not session_state.is_companion_mode()


def test_chat_uses_normal_mode_by_default(monkeypatch):
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
    assert captured[0][1] is llm_module.TOOL_SCHEMAS


def test_companion_mode_uses_limited_tools(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append((messages, tools)) or _stream("That makes sense.")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.set_mode(COMPANION)
    jarvis.chat("That was the part I missed most.", on_step=lambda m: None)
    assert captured[0][0][0]["content"] == COMPANION_PROMPT
    assert captured[0][1] is llm_module.SESSION_TOOL_SCHEMAS
    assert "Question:\n" not in captured[0][0][-1]["content"]


def test_companion_skips_planning(monkeypatch):
    jarvis = make_jarvis()
    plan_calls = []
    monkeypatch.setattr(JarvisLLM, "_make_plan", lambda self, msg: plan_calls.append(msg) or "should not run")
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda *a, **k: _stream("Okay.")
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.set_mode(COMPANION)
    jarvis.chat("first this happened, and then something else happened, after that I thought about it", on_step=lambda m: None)
    assert plan_calls == []


def test_creative_mode_uses_creative_tools(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append((messages, tools)) or _stream("I can work from the story.")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.set_mode(CREATIVE)
    jarvis.chat("Give me ideas for the next chapter.", on_step=lambda m: None)
    tool_names = {item["function"]["name"] for item in captured[0][1]}
    assert "search_creative_document" in tool_names
    assert "set_creative_document" in tool_names
    assert "search_files" not in tool_names


def test_creative_mode_can_resolve_its_tool_registry(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)
    result = jarvis._run_tool_call({"function": {"name": "clear_creative_document", "arguments": {}}})
    assert result == "Creative document cleared."


def test_companion_tool_is_resolved_from_session_registry(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(COMPANION)
    result = jarvis._run_tool_call({"function": {"name": "exit_companion_mode", "arguments": {}}})
    assert "Back to normal" in result
    assert session_state.current_mode() == NORMAL


def test_mode_is_read_fresh_each_turn(monkeypatch):
    jarvis = make_jarvis()
    captured = []
    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = lambda model, messages, tools=None, stream=False, **kwargs: (
        captured.append(tools) or _stream("done")
    )
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    session_state.set_mode(COMPANION)
    jarvis.chat("talk", on_step=lambda m: None)
    session_state.set_mode(CREATIVE)
    jarvis.chat("write", on_step=lambda m: None)
    assert captured[0] is llm_module.SESSION_TOOL_SCHEMAS
    assert captured[1] != llm_module.SESSION_TOOL_SCHEMAS


def test_companion_prompt_policy_is_explicit():
    assert "Do not ask the same question again in different words." in COMPANION_PROMPT
    assert "A response does not need to contain a question." in COMPANION_PROMPT
    assert "Never ask a question merely to keep the conversation alive." in COMPANION_PROMPT
