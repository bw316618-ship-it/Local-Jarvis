"""Window control tests."""

import platform
from unittest.mock import MagicMock

import pytest

import tools.window_control as wc


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-only unsupported-platform test")
def test_unsupported_platform_degrades_to_clean_error():
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
