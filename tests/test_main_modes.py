"""Tests for main.py mode commands and mode-aware prompt labels."""

import main
from voice import document_state, session_state


def setup_function():
    session_state.set_mode(session_state.NORMAL)
    document_state.clear_scope()


def teardown_function():
    session_state.set_mode(session_state.NORMAL)
    document_state.clear_scope()


def test_help_contains_mode_commands():
    commands = {command for command, _ in main.COMMANDS}
    assert "/talk" in commands
    assert "/creative [path]" in commands
    assert "/creative-off" in commands
    assert "/coding [path]" in commands
    assert "/coding-off" in commands


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


# --- _switch_mode: symmetric leaving-creative-scope notices ---------------
#
# Originally only /talk warned about leaving creative mode with an active
# document/project selected; going /creative -> /coding directly (or the
# reverse) gave no warning at all. All mode-switching commands now route
# through _switch_mode, so these test the shared helper directly rather
# than needing to drive the interactive REPL loop for each command.

def test_no_notice_switching_between_modes_with_nothing_active():
    session_state.set_mode(session_state.NORMAL)
    notice = main._switch_mode(session_state.CODING)
    assert notice is None
    assert session_state.current_mode() == session_state.CODING


def test_notice_when_leaving_creative_with_active_project():
    session_state.set_mode(session_state.CREATIVE)
    document_state.set_active_project("The Crownbreaker")

    notice = main._switch_mode(session_state.CODING)

    assert notice is not None
    assert "Crownbreaker" in notice
    assert "creative" in notice.lower()
    assert session_state.current_mode() == session_state.CODING


def test_notice_when_leaving_creative_with_active_document():
    session_state.set_mode(session_state.CREATIVE)
    document_state.set_active_document(r"C:\story.pdf")

    notice = main._switch_mode(session_state.COMPANION)

    assert notice is not None
    assert "document" in notice.lower()
    assert session_state.current_mode() == session_state.COMPANION


def test_no_notice_leaving_creative_with_nothing_active():
    session_state.set_mode(session_state.CREATIVE)
    # No active project or document set.
    notice = main._switch_mode(session_state.NORMAL)
    assert notice is None


def test_no_notice_re_entering_creative_mode():
    """Calling /creative or /project while already in creative mode must
    never fire the 'leaving creative' notice against itself."""
    session_state.set_mode(session_state.CREATIVE)
    document_state.set_active_project("The Crownbreaker")

    notice = main._switch_mode(session_state.CREATIVE)

    assert notice is None
    assert session_state.current_mode() == session_state.CREATIVE
    # And the scope should obviously still be intact.
    assert document_state.get_active_project() == "The Crownbreaker"


def test_no_notice_leaving_coding_mode():
    """CODING mode has no persistent state of its own (git tools take
    repo_path per call) -- nothing to warn about when leaving it, even if
    creative scope happens to be set from an earlier, unrelated session."""
    session_state.set_mode(session_state.CODING)
    notice = main._switch_mode(session_state.NORMAL)
    assert notice is None


def test_project_notice_takes_priority_over_document_wording():
    """get_creative_context's own precedence is 'document wins over
    project' for retrieval, but the notice describes whichever is
    actually there -- if a project is active (with or without a document
    also selected), the notice should name the project specifically
    rather than the more generic 'the active document' wording."""
    session_state.set_mode(session_state.CREATIVE)
    document_state.set_active_project("The Crownbreaker")
    document_state.set_active_document(r"C:\chapter2.txt")

    notice = main._switch_mode(session_state.NORMAL)

    assert "Crownbreaker" in notice
