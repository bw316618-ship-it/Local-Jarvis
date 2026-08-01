"""chat() flow: plan-skip heuristic, streaming rounds, memory recall
injected into the prompt, short-term history, and memory storage firing
exactly once regardless of which exit path is taken."""

from unittest.mock import MagicMock

import brain.llm as llm_module
from brain.llm import JarvisLLM


class FakeMemory:
    def search(self, q):
        return []


def _stream(content, tool_calls=None):
    return iter([{"message": {"content": content, "tool_calls": tool_calls}}])


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "test"
    jarvis.model = "llama3.1:8b"
    jarvis.memory = FakeMemory()
    jarvis.short_term = []
    return jarvis


def test_simple_question_skips_plan_and_tools(monkeypatch):
    jarvis = make_jarvis()
    remembered = []

    def fake_chat(model, messages, tools=None, stream=False):
        return _stream("42", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: remembered.append((u, r)))
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    steps = []
    result = jarvis.chat("what is 6*7", on_step=steps.append)

    assert result == "42"
    assert steps == [], "a short single-clause question should skip planning entirely"
    assert remembered == [("what is 6*7", "42")]
    assert jarvis.short_term == [
        {"role": "user", "content": "what is 6*7"},
        {"role": "assistant", "content": "42"},
    ]


def test_recalled_context_appears_in_the_actual_prompt(monkeypatch):
    jarvis = make_jarvis()
    captured = []

    def fake_chat(model, messages, tools=None, stream=False):
        captured.append(messages[1]["content"])
        return _stream("Continuing with JWT.", None)

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: ["User asked: what auth method\nJarvis answered: We chose JWT."])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: ["[preference] Prefers concise answers"])

    jarvis.chat("continue the auth system", on_step=lambda m: None)

    assert "We chose JWT" in captured[0]
    assert "Prefers concise answers" in captured[0]


def test_plan_is_emitted_for_a_multi_step_request(monkeypatch):
    jarvis = make_jarvis()
    from tools.tools import TOOL_FUNCTIONS
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_current_time", lambda: "Sunday")

    round_count = [0]

    def fake_chat(model, messages, tools=None, stream=False):
        if tools is None and not stream:
            return {"message": {"content": "1. Check time\n2. Report it"}}
        round_count[0] += 1
        if round_count[0] == 1:
            return _stream("", [{"function": {"name": "get_current_time", "arguments": {}}}])
        return _stream("It is Sunday.", None)

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


def test_sentences_are_streamed_incrementally(monkeypatch):
    jarvis = make_jarvis()

    def fake_chat(model, messages, tools=None, stream=False):
        return iter(
            [
                {"message": {"content": "Hello. ", "tool_calls": None}},
                {"message": {"content": "How are you?", "tool_calls": None}},
            ]
        )

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    sentences = []
    result = jarvis.chat("hi", on_sentence=sentences.append)

    assert result == "Hello. How are you?"
    assert sentences == ["Hello.", "How are you?"], "sentence boundaries should flush as they complete"


def test_memory_is_stored_on_the_round_limit_fallback_path(monkeypatch):
    jarvis = make_jarvis()
    from tools.tools import TOOL_FUNCTIONS
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_current_time", lambda: "time")

    remembered = []
    call_count = [0]

    def fake_chat(model, messages, tools=None, stream=False):
        call_count[0] += 1
        if call_count[0] >= llm_module.MAX_TOOL_ROUNDS:
            return _stream("FALLBACK ANSWER", None)
        return _stream("", [{"function": {"name": "get_current_time", "arguments": {}}}])

    fake_client = MagicMock()
    fake_client.chat.side_effect = fake_chat
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: remembered.append((u, r)))
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3: [])

    result = jarvis.chat("loop forever", on_step=lambda m: None)

    assert result == "FALLBACK ANSWER"
    assert remembered == [("loop forever", "FALLBACK ANSWER")]