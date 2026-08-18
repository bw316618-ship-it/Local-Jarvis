"""Tier 1 tools: local task/calendar store, battery status, session
control (mute + end-session flags), and confirmation-gating for the new
risky tools (delete_task, open_pdf, control_media, end_session)."""

from unittest.mock import MagicMock

import tools.calendar_tool as ct
from voice import session_state


def _reset_session_state():
    session_state.unmute()
    session_state.clear_end_request()


# --- calendar_tool -----------------------------------------------------

def test_add_and_list_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")

    result = ct.add_task("Buy milk", "2026-08-20")
    assert "Buy milk" in result and "2026-08-20" in result

    listing = ct.list_tasks()
    assert "Buy milk" in listing
    assert "[ ]" in listing


def test_list_tasks_filters_by_due_date(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")
    ct.add_task("Due today", "2026-08-20")
    ct.add_task("Due later", "2026-09-01")

    result = ct.list_tasks("2026-08-20")
    assert "Due today" in result
    assert "Due later" not in result


def test_completed_tasks_excluded_from_default_pending_view(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")
    ct.add_task("Finish report", "2026-08-20")
    ct.complete_task("finish report")

    assert "Finish report" not in ct.list_tasks()
    assert "[done] Finish report" in ct.list_tasks("2026-08-20")


def test_ambiguous_title_match_lists_candidates_instead_of_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")
    ct.add_task("Call Alice", "2026-08-20")
    ct.add_task("Call Bob", "2026-08-21")

    result = ct.complete_task("call")
    assert "Multiple tasks match" in result
    assert "Call Alice" in result and "Call Bob" in result


def test_delete_task_actually_removes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")
    ct.add_task("Temporary", "2026-08-20")
    result = ct.delete_task("temporary")
    assert "Deleted" in result
    assert "Temporary" not in ct.list_tasks("2026-08-20")


def test_unparseable_date_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "CALENDAR_PATH", tmp_path / "cal.ics")
    result = ct.add_task("X", "not-a-real-date-at-all-xyz")
    assert "Could not understand the date" in result


def test_calendar_survives_a_corrupted_file(tmp_path, monkeypatch):
    """A previous crash mid-write, or manual edit, could leave the .ics
    file corrupted -- the tool should start fresh rather than error out
    on every subsequent call."""
    bad_path = tmp_path / "cal.ics"
    bad_path.write_text("not a valid ics file{{{")
    monkeypatch.setattr(ct, "CALENDAR_PATH", bad_path)

    result = ct.add_task("Recovered", "2026-08-20")
    assert "Recovered" in result


# --- diagnostics: battery -----------------------------------------------

def test_battery_status_handles_no_battery_present(monkeypatch):
    import tools.diagnostics as diag
    monkeypatch.setattr(diag.psutil, "sensors_battery", lambda: None)
    assert "No battery detected" in diag.battery_status()


def test_battery_status_reports_percentage_and_plugged_state(monkeypatch):
    import tools.diagnostics as diag
    fake_battery = MagicMock(percent=87.0, power_plugged=True, secsleft=diag.psutil.POWER_TIME_UNLIMITED)
    monkeypatch.setattr(diag.psutil, "sensors_battery", lambda: fake_battery)
    result = diag.battery_status()
    assert "87%" in result and "plugged in" in result


# --- session control: mute + end-session flags --------------------------

def test_mute_and_unmute_toggle_shared_state():
    _reset_session_state()
    from tools.session_control import mute_jarvis, unmute_jarvis

    assert not session_state.is_muted()
    mute_jarvis()
    assert session_state.is_muted()
    unmute_jarvis()
    assert not session_state.is_muted()
    _reset_session_state()


def test_end_session_sets_flag_without_raising():
    _reset_session_state()
    from tools.session_control import end_session

    assert not session_state.is_end_requested()
    result = end_session()
    assert isinstance(result, str)  # must not raise -- see session_state's docstring
    assert session_state.is_end_requested()
    _reset_session_state()


def test_voice_speak_is_a_noop_while_muted(monkeypatch):
    from voice.voice import JarvisVoice

    _reset_session_state()
    jv = JarvisVoice.__new__(JarvisVoice)
    called = []
    monkeypatch.setattr(jv, "_get_tts_voice", lambda: called.append(True), raising=False)

    session_state.mute()
    jv.speak("hello")
    assert called == [], "speak() must not touch the TTS voice at all while muted"
    _reset_session_state()


# --- confirmation gating for the new risky tools -------------------------

def test_new_risky_tools_are_registered_risky():
    from tools.tools import RISKY_TOOLS
    assert {"delete_task", "open_pdf", "control_media", "end_session"} <= RISKY_TOOLS


def test_new_safe_tools_are_not_registered_risky():
    from tools.tools import RISKY_TOOLS
    safe = {
        "get_battery_level", "get_location", "add_task", "list_tasks",
        "complete_task", "find_datasheet", "get_now_playing",
        "mute_jarvis", "unmute_jarvis",
    }
    assert not (safe & RISKY_TOOLS)
