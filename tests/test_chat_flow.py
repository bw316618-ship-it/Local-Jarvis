"""chat() flow: plan display, memory recall injected into the prompt, and
memory storage firing exactly once regardless of which exit path is taken."""

from unittest.mock import MagicMock

import brain.llm as llm_module
from brain.llm import JarvisLLM


class FakeMemory:
    def search(self, q):
        return []


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "test"
    jarvis.model = "llama3.1:8b"
    jarvis.memory = FakeMemory()
    return jarvis


def test_simple_question_skips_plan_and_tools(monkeypatch):
    jarvis = make_jarvis()
    remembered = []

    def fake_chat(model, messages, tools=None):
        if tools is None:
            return {"message": {"content": "No plan needed."}}
        return {"message": {"content": "42", "tool_calls": None}}

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: remembered.append((u, r)))
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    steps = []
    result = jarvis.chat("what is 6*7", on_step=steps.append)

    assert result == "42"
    assert steps == [], "no plan and no tool calls means nothing should be emitted"
    assert remembered == [("what is 6*7", "42")]


def test_recalled_context_appears_in_the_actual_prompt(monkeypatch):
    jarvis = make_jarvis()
    captured = []

    def fake_chat(model, messages, tools=None):
        if tools is None:
            return {"message": {"content": "No plan needed."}}
        captured.append(messages[1]["content"])
        return {"message": {"content": "Continuing with JWT.", "tool_calls": None}}

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: ["User asked: what auth method\nJarvis answered: We chose JWT."])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: ["[preference] Prefers concise answers"])

    jarvis.chat("continue the auth system", on_step=lambda m: None)

    assert "We chose JWT" in captured[0]
    assert "Prefers concise answers" in captured[0]


def test_plan_is_emitted_and_tool_executes_across_rounds(monkeypatch):
    jarvis = make_jarvis()
    from tools.tools import TOOL_FUNCTIONS
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_current_time", lambda: "Sunday")

    call_sequence = []

    def fake_chat(model, messages, tools=None):
        call_sequence.append(tools is not None)
        if tools is None:
            return {"message": {"content": "1. Check time\n2. Report it"}}
        tool_round = call_sequence.count(True)
        if tool_round == 1:
            return {"message": {"content": "", "tool_calls": [{"function": {"name": "get_current_time", "arguments": {}}}]}}
        return {"message": {"content": "It is Sunday.", "tool_calls": None}}

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    steps = []
    result = jarvis.chat("what time is it and tell me", on_step=steps.append)

    assert result == "It is Sunday."
    assert any(s.startswith("Plan:") for s in steps)
    assert any("get_current_time" in s for s in steps)


def test_memory_is_stored_on_the_round_limit_fallback_path(monkeypatch):
    """The round-limit fallback is a second, separate return path from the
    main loop -- memory storage must fire there too, not just on the
    normal early-return path."""
    jarvis = make_jarvis()
    from tools.tools import TOOL_FUNCTIONS
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_current_time", lambda: "time")

    remembered = []
    call_count = [0]

    def fake_chat(model, messages, tools=None):
        if tools is None:
            return {"message": {"content": "No plan needed."}}
        call_count[0] += 1
        if call_count[0] >= llm_module.MAX_TOOL_ROUNDS:
            return {"message": {"content": "FALLBACK ANSWER"}}
        return {"message": {"content": "", "tool_calls": [{"function": {"name": "get_current_time", "arguments": {}}}]}}

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: remembered.append((u, r)))
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    result = jarvis.chat("loop forever", on_step=lambda m: None)

    assert result == "FALLBACK ANSWER"
    assert remembered == [("loop forever", "FALLBACK ANSWER")], (
        "the fallback exit path must store memory too -- this is exactly the kind "
        "of bug that's easy to introduce silently when there are two return paths"
    )
