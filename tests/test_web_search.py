"""tools/web.py -- web_search's success/empty/error paths and its local
retry loop.

web_search imports ddgs.DDGS lazily inside the function body (so the
tool degrades gracefully if the package isn't installed), so tests
patch ddgs.DDGS directly rather than tools.web.DDGS -- there's no
module-level binding in tools.web to patch.
"""

import builtins
from unittest.mock import MagicMock, patch

import pytest

import ddgs
import tools.web as web


def _ddgs_returning(results):
    """A fake DDGS context manager whose .text(...) returns `results`."""
    instance = MagicMock()
    instance.text.return_value = results
    instance.__enter__.return_value = instance
    instance.__exit__.return_value = False
    return MagicMock(return_value=instance)


def test_search_success_formats_title_snippet_and_url():
    results = [
        {"title": "Example", "body": "An example result.", "href": "https://example.test"},
    ]
    with patch.object(ddgs, "DDGS", _ddgs_returning(results)):
        output = web.web_search("test query")

    assert "Example" in output
    assert "An example result." in output
    assert "https://example.test" in output


def test_search_multiple_results_all_present():
    results = [
        {"title": "One", "body": "First.", "href": "https://one.test"},
        {"title": "Two", "body": "Second.", "href": "https://two.test"},
    ]
    with patch.object(ddgs, "DDGS", _ddgs_returning(results)):
        output = web.web_search("test query")

    assert "One" in output and "Two" in output


def test_no_results_returns_friendly_message():
    with patch.object(ddgs, "DDGS", _ddgs_returning([])):
        output = web.web_search("something obscure")

    assert "No results found" in output
    assert "something obscure" in output


def test_missing_ddgs_package_returns_friendly_message(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("no module named ddgs")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    output = web.web_search("anything")

    assert "not installed" in output.lower()
    assert "pip install" in output.lower()


# --- retry behavior ------------------------------------------------------

def test_transient_failure_then_success_is_retried(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda s: None)

    ok_instance = MagicMock()
    ok_instance.text.return_value = [
        {"title": "Recovered", "body": "Worked on retry.", "href": "https://ok.test"}
    ]
    ok_instance.__enter__.return_value = ok_instance
    ok_instance.__exit__.return_value = False

    call_count = {"n": 0}

    def flaky_ddgs():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("transient blip")
        return ok_instance

    with patch.object(ddgs, "DDGS", side_effect=flaky_ddgs):
        output = web.web_search("test query")

    assert "Recovered" in output
    assert call_count["n"] == 2


def test_gives_up_after_configured_attempts_and_reports_last_error(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda s: None)

    from config import CONFIG as real_config
    monkeypatch.setitem(real_config, "network_retry_attempts", 2)

    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise ConnectionError(f"still down (attempt {call_count['n']})")

    with patch.object(ddgs, "DDGS", side_effect=always_fails):
        output = web.web_search("test query")

    assert "Web search failed" in output
    assert call_count["n"] == 2


def test_does_not_retry_when_attempts_is_one(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda s: None)

    from config import CONFIG as real_config
    with patch.dict(real_config, {"network_retry_attempts": 1}):
        call_count = {"n": 0}

        def always_fails():
            call_count["n"] += 1
            raise ConnectionError("down")

        with patch.object(ddgs, "DDGS", side_effect=always_fails):
            web.web_search("test query")

        assert call_count["n"] == 1
