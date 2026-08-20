"""Tests for wiring Creative Mode generation tools into Jarvis."""

from unittest.mock import MagicMock

import brain.llm as llm_module
from brain.llm import JarvisLLM
from brain.mode_config import COMPANION, CREATIVE, NORMAL, get_mode_config
from tools import creative_generation
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
    jarvis.system_prompt = "TASK"
    jarvis.companion_system_prompt = "COMPANION"
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


def test_creative_mode_exposes_generation_tools():
    names = {
        item["function"]["name"]
        for item in get_mode_config(CREATIVE)["tools"]
    }

    assert "get_creative_context" in names
    assert "build_chapter_ideas_context" in names
    assert "build_scene_context" in names


def test_normal_mode_does_not_expose_generation_tools():
    names = {
        item["function"]["name"]
        for item in get_mode_config(NORMAL)["tools"]
    }

    assert "get_creative_context" not in names
    assert "build_chapter_ideas_context" not in names
    assert "build_scene_context" not in names


def test_companion_mode_does_not_expose_generation_tools():
    names = {
        item["function"]["name"]
        for item in get_mode_config(COMPANION)["tools"]
    }

    assert "get_creative_context" not in names
    assert "build_chapter_ideas_context" not in names
    assert "build_scene_context" not in names


def test_creative_registry_resolves_generation_tools():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    registry, risky = jarvis._tool_registry_for_mode(CREATIVE)

    assert registry["get_creative_context"]
    assert registry["build_chapter_ideas_context"]
    assert registry["build_scene_context"]
    assert "get_creative_context" not in risky


def test_creative_generation_tools_are_not_executed_in_other_modes():
    jarvis = make_jarvis()

    session_state.set_mode(NORMAL)
    registry, _ = jarvis._tool_registry_for_mode(NORMAL)
    assert "build_scene_context" not in registry

    session_state.set_mode(COMPANION)
    registry, _ = jarvis._tool_registry_for_mode(COMPANION)
    assert "build_scene_context" not in registry


def test_chapter_ideas_tool_can_be_called_through_llm_registry(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)
    document_state.set_active_document(r"C:\story.pdf")

    monkeypatch.setattr(
        llm_module,
        "TOOL_CALL_TIMEOUT_SECONDS",
        10,
    )
    monkeypatch.setitem(
        creative_generation.CREATIVE_GENERATION_TOOL_FUNCTIONS,
        "build_chapter_ideas_context",
        lambda request, k=10: (
            "CANON: Arin must choose between the Crown and the Weaver."
        ),
    )

    result = jarvis._run_tool_call(
        {
            "function": {
                "name": "build_chapter_ideas_context",
                "arguments": {"request": "What could happen next?"},
            }
        }
    )

    assert "CANON: Arin must choose" in result


def test_scene_tool_can_be_called_through_llm_registry(monkeypatch):
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)
    document_state.set_active_document(r"C:\story.pdf")

    monkeypatch.setattr(
        llm_module,
        "TOOL_CALL_TIMEOUT_SECONDS",
        10,
    )
    monkeypatch.setitem(
        creative_generation.CREATIVE_GENERATION_TOOL_FUNCTIONS,
        "build_scene_context",
        lambda request, k=10: (
            "CANON: The confrontation occurs beneath the eastern citadel."
        ),
    )

    result = jarvis._run_tool_call(
        {
            "function": {
                "name": "build_scene_context",
                "arguments": {"request": "Write the confrontation."},
            }
        }
    )

    assert "beneath the eastern citadel" in result


def test_creative_toolset_has_document_and_generation_layers():
    names = {
        item["function"]["name"]
        for item in get_mode_config(CREATIVE)["tools"]
    }

    assert "ingest_creative_document" in names
    assert "search_creative_document" in names
    assert "build_chapter_ideas_context" in names
    assert "build_scene_context" in names
