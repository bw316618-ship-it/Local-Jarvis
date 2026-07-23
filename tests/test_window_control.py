"""Window control: match/no-match handling and graceful degradation on
unsupported platforms (this genuinely triggers on Linux, where PyGetWindow
raises NotImplementedError at import time)."""

from unittest.mock import MagicMock

import tools.window_control as wc


def test_unsupported_platform_degrades_to_clean_error():
    """No mocking here -- PyGetWindow genuinely doesn't support Linux, so
    this exercises the real error path, not a simulated one."""
    result = wc.list_windows()
    assert "isn't available" in result
    assert "Traceback" not in result


def test_focus_window_matches_and_activates(monkeypatch):
    window = MagicMock()
    window.title = "Google Chrome - localhost:3000"
    fake_gw = MagicMock()
    fake_gw.getWindowsWithTitle.return_value = [window]
    monkeypatch.setattr(wc, "_get_gw", lambda: fake_gw)

    result = wc.focus_window("Chrome")
    assert window.activate.called
    assert "Focused" in result


def test_no_matching_window_returns_a_clear_message(monkeypatch):
    fake_gw = MagicMock()
    fake_gw.getWindowsWithTitle.return_value = []
    monkeypatch.setattr(wc, "_get_gw", lambda: fake_gw)

    result = wc.focus_window("Nonexistent App")
    assert "No open window found" in result


def test_list_windows_filters_blank_titles(monkeypatch):
    fake_gw = MagicMock()
    fake_gw.getAllTitles.return_value = ["Chrome", "", "  ", "VS Code"]
    monkeypatch.setattr(wc, "_get_gw", lambda: fake_gw)

    result = wc.list_windows()
    assert "Chrome" in result
    assert "VS Code" in result
