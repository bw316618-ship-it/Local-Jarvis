"""Regression tests for Creative Mode document initialization."""

from unittest.mock import MagicMock

import brain.llm as llm_module
from brain.llm import JarvisLLM
from brain.mode_config import (
    COMPANION,
    COMPANION_PROMPT,
    CREATIVE,
    CREATIVE_PROMPT,
    NORMAL,
)
from voice import document_state, session_state


def setup_function():
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()


def teardown_function():
    session_state.set_mode(NORMAL)
    document_state.clear_active_document()


def _stream(content="", tool_calls=None):
    return iter(
        [
            {
                "message": {
                    "content": content,
                    "tool_calls": tool_calls,
                }
            }
        ]
    )


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK-MODE-PROMPT"
    jarvis.companion_system_prompt = COMPANION_PROMPT
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock(search=lambda *a, **k: [])
    jarvis.short_term = []
    return jarvis


def test_creative_prompt_requires_direct_story_pdf_ingestion():
    assert "Immediately call ingest_creative_document" in CREATIVE_PROMPT
    assert "Do not call general file-management tools for this." in CREATIVE_PROMPT
    assert "Do not open the file in an external application." in CREATIVE_PROMPT
    assert "Do not add it to the general workspace." in CREATIVE_PROMPT
    assert "Do not make a plan before ingestion." in CREATIVE_PROMPT
    assert "Do not ask the user what they want done with the document." in CREATIVE_PROMPT


def test_creative_prompt_requires_exact_user_supplied_path():
    assert "Use the exact path supplied by the user." in CREATIVE_PROMPT
    assert "Do not alter, normalize into another filename, or invent a different path." in CREATIVE_PROMPT


def test_creative_prompt_blocks_general_memory_from_replacing_document_context():
    assert "Do not substitute general computer-file search or unrelated remembered information" in CREATIVE_PROMPT


def test_creative_mode_does_not_run_the_multi_step_planner():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    plan_calls = []

    jarvis._make_plan = lambda message: (
        plan_calls.append(message) or "this must never run"
    )

    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = (
        lambda *args, **kwargs: _stream("I would ingest the document.")
    )

    jarvis.chat(
        'This is my story PDF: "C:\\\\Users\\\\me\\\\story.pdf"',
        on_step=lambda _: None,
    )

    assert plan_calls == []


def test_creative_pdf_message_exposes_ingestion_tool_to_model(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    captured = []

    jarvis.client = MagicMock()
    jarvis.client.chat.side_effect = (
        lambda model, messages, tools=None, stream=False, **kwargs: (
            captured.append((messages, tools))
            or _stream("I will ingest the story.")
        )
    )

    monkeypatch.setattr(llm_module, "remember_turn", lambda *a, **k: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])

    message = 'This is my story PDF: "C:\\\\Users\\\\me\\\\story.pdf"'
    jarvis.chat(message, on_step=lambda _: None)

    tool_names = {
        item["function"]["name"]
        for item in captured[0][1]
    }

    assert "ingest_creative_document" in tool_names
    assert "write_file" not in tool_names
    assert "open_application" not in tool_names


def test_creative_document_initialization_instructions_are_not_in_normal_mode():
    from brain.mode_config import get_mode_config

    assert "ingest_creative_document" not in (
        get_mode_config(NORMAL)["prompt"] or ""
    )


def test_companion_prompt_remains_unchanged_by_creative_document_rules():
    assert "ingest_creative_document" not in COMPANION_PROMPT
    assert "Do not ask the same question again in different words." in COMPANION_PROMPT
