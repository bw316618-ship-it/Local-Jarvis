import brain.persona_lines as persona_lines
import tools.session_control as sc
from voice import session_state


def setup_function(_):
    # session_state is a process-wide global here (see tools/session_control.py's
    # own docstring on this) -- reset it so tests don't leak into each other.
    session_state.unmute()
    session_state.exit_companion_mode()
    session_state.exit_heavy_brain()
    session_state.clear_end_request()


def teardown_function(_):
    session_state.unmute()
    session_state.exit_companion_mode()
    session_state.exit_heavy_brain()
    session_state.clear_end_request()


def test_mute_jarvis_mutes_state_and_returns_a_persona_line():
    result = sc.mute_jarvis()
    assert session_state.is_muted() is True
    assert result in persona_lines.POOLS["mute"]


def test_unmute_jarvis_unmutes_state_and_returns_a_persona_line():
    session_state.mute()
    result = sc.unmute_jarvis()
    assert session_state.is_muted() is False
    assert result in persona_lines.POOLS["unmute"]


def test_end_session_requests_end_and_returns_a_persona_line():
    result = sc.end_session()
    assert session_state.is_end_requested() is True
    assert result in persona_lines.POOLS["end_session"]


def test_enter_and_exit_companion_mode_return_persona_lines():
    assert sc.enter_companion_mode() in persona_lines.POOLS["enter_companion"]
    assert session_state.is_companion_mode() is True

    assert sc.exit_companion_mode() in persona_lines.POOLS["exit_companion"]
    assert session_state.is_companion_mode() is False


def test_enter_and_exit_creative_mode_return_persona_lines():
    assert sc.enter_creative_mode() in persona_lines.POOLS["enter_creative"]
    assert sc.exit_creative_mode() in persona_lines.POOLS["exit_creative"]


def test_enter_and_exit_coding_mode_return_persona_lines():
    assert sc.enter_coding_mode() in persona_lines.POOLS["enter_coding"]
    assert sc.exit_coding_mode() in persona_lines.POOLS["exit_coding"]


def test_enter_and_exit_heavy_brain_return_persona_lines():
    assert sc.enter_heavy_brain() in persona_lines.POOLS["enter_heavy_brain"]
    assert session_state.is_heavy_brain() is True

    assert sc.exit_heavy_brain() in persona_lines.POOLS["exit_heavy_brain"]
    assert session_state.is_heavy_brain() is False
