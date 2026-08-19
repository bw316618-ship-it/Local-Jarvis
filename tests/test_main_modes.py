"""Tests for main.py mode commands and mode-aware prompt labels."""

import main
from voice import session_state


def test_help_contains_mode_commands():
    commands = {command for command, _ in main.COMMANDS}
    assert "/talk" in commands
    assert "/creative [path]" in commands
    assert "/creative-off" in commands


def test_mode_labels(capsys):
    session_state.set_mode(session_state.NORMAL)
    main._print_mode()
    assert "Mode: normal" in capsys.readouterr().out

    session_state.set_mode(session_state.COMPANION)
    main._print_mode()
    assert "Mode: companion" in capsys.readouterr().out

    session_state.set_mode(session_state.CREATIVE)
    main._print_mode()
    assert "Mode: creative" in capsys.readouterr().out


def test_session_end_handler_ignores_clear_state(monkeypatch):
    session_state.clear_end_request()
    assert main._handle_possible_session_end() is False
