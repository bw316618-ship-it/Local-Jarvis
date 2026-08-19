"""Tests for deterministic Creative Mode document initialization."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import brain.llm as llm_module
from brain.llm import (
    JarvisLLM,
    _extract_creative_document_path,
)
from brain.mode_config import COMPANION, COMPANION_PROMPT, CREATIVE, NORMAL
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


def test_extracts_quoted_windows_pdf_path():
    message = (
        'This is my story PDF: '
        '"C:\\Users\\ironm\\Downloads\\The Crown of Endless Dawn and Crownbreaker.pdf"'
    )

    assert _extract_creative_document_path(message) == (
        r"C:\Users\ironm\Downloads\The Crown of Endless Dawn and Crownbreaker.pdf"
    )


def test_extracts_unquoted_supported_document_path():
    message = (
        r"This is my story: C:\Users\ironm\Downloads\story.md"
    )

    assert _extract_creative_document_path(message) == (
        r"C:\Users\ironm\Downloads\story.md"
    )


def test_does_not_treat_arbitrary_pdf_mentions_as_ingestion():
    message = (
        r"I found a PDF at C:\Users\ironm\Downloads\story.pdf "
        "but I am not giving it to you yet."
    )

    assert _extract_creative_document_path(message) is None


def test_does_not_extract_unsupported_document_types():
    message = r"This is my story: C:\Users\ironm\Downloads\story.docx"

    assert _extract_creative_document_path(message) is None


def test_deterministic_creative_ingestion_happens_before_planning():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    events = []

    jarvis._make_plan = MagicMock(
        side_effect=lambda _: events.append("plan") or "plan"
    )

    jarvis._run_tool_call = MagicMock(
        side_effect=lambda call: (
            events.append(call["function"]["name"])
            or "Creative document ingested."
        )
    )

    message = (
        'This is my story PDF: '
        '"C:\\Users\\ironm\\Downloads\\story.pdf"'
    )

    result = jarvis.chat(message, on_step=lambda text: None)

    assert result == "Creative document ingested."
    assert events == ["ingest_creative_document"]
    jarvis._make_plan.assert_not_called()


def test_deterministic_ingestion_uses_exact_supplied_path():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    jarvis._run_tool_call = MagicMock(
        return_value="Creative document ingested."
    )

    message = (
        'This is my story PDF: '
        '"C:\\Users\\ironm\\Downloads\\The Crown of Endless Dawn and Crownbreaker.pdf"'
    )

    jarvis.chat(message, on_step=lambda text: None)

    call = jarvis._run_tool_call.call_args.args[0]
    assert call["function"]["name"] == "ingest_creative_document"
    assert call["function"]["arguments"]["path"] == (
        r"C:\Users\ironm\Downloads\The Crown of Endless Dawn and Crownbreaker.pdf"
    )


def test_deterministic_ingestion_only_runs_in_creative_mode():
    jarvis = make_jarvis()
    session_state.set_mode(COMPANION)

    jarvis._run_tool_call = MagicMock()

    message = (
        'This is my story PDF: '
        '"C:\\Users\\ironm\\Downloads\\story.pdf"'
    )

    # Avoid invoking the real Ollama path; the assertion is about the
    # deterministic ingestion gate.
    with patch.object(
        jarvis,
        "_stream_round",
        return_value=("ordinary response", None),
    ):
        result = jarvis.chat(message, on_step=lambda text: None)

    assert result == "ordinary response"
    jarvis._run_tool_call.assert_not_called()


def test_creative_document_initialization_does_not_use_general_file_tools():
    from brain.mode_config import get_mode_config

    names = {
        item["function"]["name"]
        for item in get_mode_config(CREATIVE)["tools"]
    }

    assert "ingest_creative_document" in names
    assert "write_file" not in names
    assert "open_application" not in names


def test_companion_mode_prompt_is_unchanged():
    assert "ingest_creative_document" not in COMPANION_PROMPT
