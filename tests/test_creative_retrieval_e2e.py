"""End-to-end regression tests for Creative Mode document retrieval."""

from unittest.mock import MagicMock, patch

from brain.llm import JarvisLLM
from brain.mode_config import COMPANION_PROMPT, CREATIVE, NORMAL, get_mode_config
from voice import document_state, session_state


def setup_function():
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()


def teardown_function():
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK-MODE-PROMPT"
    jarvis.companion_system_prompt = COMPANION_PROMPT
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


def test_creative_followup_exposes_document_search_tool():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    captured = {}

    def fake_stream(messages, tools, on_token=None, on_sentence=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return "I need to inspect the story.", None

    jarvis._stream_round = fake_stream

    with patch(
        "brain.llm.get_embedder",
        side_effect=RuntimeError("embedding unavailable in unit test"),
    ), patch(
        "brain.llm.remember_turn",
    ), patch(
        "brain.llm.recall",
        return_value=[],
    ), patch(
        "brain.llm.recall_facts",
        return_value=[],
    ):
        document_state.set_active_document(
            r"C:\Users\ironm\Downloads\story.pdf"
        )

        result = jarvis.chat(
            "Who is Arin?",
            on_step=lambda _: None,
        )

    assert result == "I need to inspect the story."

    tool_names = {
        item["function"]["name"]
        for item in captured["tools"]
    }

    assert "search_creative_document" in tool_names
    assert "ingest_creative_document" in tool_names

    prompt = captured["messages"][-1]["content"]

    assert r"C:\Users\ironm\Downloads\story.pdf" in prompt
    assert "Who is Arin?" in prompt


def test_creative_search_tool_receives_active_document_scope():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    active_story = r"C:\Users\ironm\Downloads\story.pdf"
    document_state.set_active_document(active_story)

    jarvis._run_tool_call = MagicMock(
        return_value=(
            "Relevant passages from the active story:\n"
            "[1]\n"
            "Arin is the last Crownkeeper."
        )
    )

    result = jarvis._run_tool_call(
        {
            "function": {
                "name": "search_creative_document",
                "arguments": {"query": "Arin", "k": 6},
            }
        }
    )

    assert "Arin is the last Crownkeeper." in result

    call = jarvis._run_tool_call.call_args.args[0]
    assert call["function"]["name"] == "search_creative_document"


def test_creative_search_tool_is_available_but_general_file_search_is_not():
    names = {
        item["function"]["name"]
        for item in get_mode_config(CREATIVE)["tools"]
    }

    assert "search_creative_document" in names
    assert "search_files" not in names


def test_active_document_is_passed_to_creative_context():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    active_story = r"C:\Users\ironm\Downloads\story.pdf"
    document_state.set_active_document(active_story)

    captured = {}

    def fake_stream(messages, tools, on_token=None, on_sentence=None):
        captured["messages"] = messages
        return "Story-grounded response.", None

    jarvis._stream_round = fake_stream

    with patch(
        "brain.llm.get_embedder",
        side_effect=RuntimeError("embedding unavailable in unit test"),
    ), patch(
        "brain.llm.remember_turn",
    ), patch(
        "brain.llm.recall",
        return_value=[],
    ), patch(
        "brain.llm.recall_facts",
        return_value=[],
    ):
        result = jarvis.chat(
            "What should happen next?",
            on_step=lambda _: None,
        )

    assert result == "Story-grounded response."

    user_context = captured["messages"][-1]["content"]

    assert "Active creative document:" in user_context
    assert active_story in user_context
    assert "What should happen next?" in user_context
