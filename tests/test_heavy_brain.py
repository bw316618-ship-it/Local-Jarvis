"""Heavy-brain model-tier toggle tests.

Covers voice/session_state.py's brain-tier flag and its exposure as
enter_heavy_brain/exit_heavy_brain tools in tools/session_control.py.
config.get_model_for_mode's precedence rules and brain/llm.py's chat()
actually resolving self.model from the flag are covered in
tests/test_mode_models.py alongside the existing mode_models tests,
since it's the same "which model for this turn" mechanism.
"""

import pytest

from voice import session_state
from tools.session_control import (
    enter_heavy_brain,
    exit_heavy_brain,
    SESSION_TOOL_FUNCTIONS,
    SESSION_TOOL_SCHEMAS,
    SESSION_RISKY_TOOLS,
)


@pytest.fixture(autouse=True)
def reset_brain_tier():
    session_state.exit_heavy_brain()
    yield
    session_state.exit_heavy_brain()


def test_flag_starts_fast_and_toggles():
    assert not session_state.is_heavy_brain()
    session_state.enter_heavy_brain()
    assert session_state.is_heavy_brain()
    session_state.exit_heavy_brain()
    assert not session_state.is_heavy_brain()


def test_current_brain_tier_reports_the_named_tier():
    assert session_state.current_brain_tier() == session_state.BRAIN_FAST
    session_state.enter_heavy_brain()
    assert session_state.current_brain_tier() == session_state.BRAIN_HEAVY


def test_set_brain_tier_rejects_unknown_tier():
    with pytest.raises(ValueError):
        session_state.set_brain_tier("ultra")


def test_registered_and_not_risky():
    assert "enter_heavy_brain" in SESSION_TOOL_FUNCTIONS
    assert "exit_heavy_brain" in SESSION_TOOL_FUNCTIONS
    assert "enter_heavy_brain" not in SESSION_RISKY_TOOLS
    assert "exit_heavy_brain" not in SESSION_RISKY_TOOLS


def test_schema_and_function_names_match():
    schema_names = {s["function"]["name"] for s in SESSION_TOOL_SCHEMAS}
    assert "enter_heavy_brain" in schema_names
    assert "exit_heavy_brain" in schema_names


def test_tool_functions_flip_the_same_flag_the_model_can_call():
    enter_heavy_brain()
    assert session_state.is_heavy_brain()
    exit_heavy_brain()
    assert not session_state.is_heavy_brain()


def test_tool_functions_return_a_confirmation_string():
    assert "heavy" in enter_heavy_brain().lower()
    assert "fast" in exit_heavy_brain().lower() or "default" in exit_heavy_brain().lower()
