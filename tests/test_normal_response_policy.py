from unittest.mock import MagicMock

from brain.llm import JarvisLLM, _is_trivial_conversation
from brain.mode_config import NORMAL
from voice import session_state


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    JarvisLLM.__init__(
        jarvis,
        model="qwen3:8b",
        confirm_callback=lambda name, args: True,
    )
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    jarvis.confirm_callback = lambda name, args: True
    return jarvis


def test_greetings_are_trivial():
    assert _is_trivial_conversation("hi")
    assert _is_trivial_conversation("hello")
    assert _is_trivial_conversation("hey")
    assert _is_trivial_conversation("good morning")


def test_normal_questions_are_not_trivial():
    assert not _is_trivial_conversation("What is the weather?")
    assert not _is_trivial_conversation("Explain recursion.")
    assert not _is_trivial_conversation("What did I say about my story?")


def test_trivial_message_does_not_query_long_term_memory(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(NORMAL)

    jarvis._stream_round = lambda messages, tools, **kwargs: (
        "Hello.",
        None,
    )

    jarvis.memory.search.reset_mock()

    monkeypatch.setattr(
        "brain.llm.remember_turn",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "brain.llm.recall",
        lambda *args, **kwargs: [],
    )

    monkeypatch.setattr(
        "brain.llm.recall_facts",
        lambda *args, **kwargs: [],
    )

    result = jarvis.chat(
        "hi",
        on_step=lambda _: None,
    )

    assert result == "Hello."
    jarvis.memory.search.assert_not_called()


def test_normal_system_prompt_forbids_meta_responses():
    jarvis = make_jarvis()

    prompt = jarvis.system_prompt

    assert "Do not describe your internal reasoning" in prompt
    assert "the user has greeted" in prompt
    assert "Answer simple conversational messages simply" in prompt