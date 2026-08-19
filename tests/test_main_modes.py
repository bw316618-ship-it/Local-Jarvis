"""Tests for main.py mode commands and mode-aware prompt labels."""

from unittest.mock import MagicMock

import main
from voice import session_state


def test_help_contains_mode_commands():
    commands = {command for command, _ in main.COMMANDS}

    assert "/talk" in commands
    assert "/creative [path]" in commands
    assert "/creative-off" in commands


def test_mode_labels():
    session_state.set_mode(session_state.NORMAL)
    assert "normal" in main.__dict__["_print_mode"].__name__


def test_session_end_handler_ignores_clear_state(monkeypatch):
    session_state.clear_end_request()
    assert main._handle_possible_session_end() is False
