"""tools/datasheet.py -- find_datasheet's success/empty/error paths and
its local retry loop.

find_datasheet imports ddgs.DDGS lazily inside the function body (so
the tool degrades gracefully if the package isn't installed), so
tests patch ddgs.DDGS directly rather than tools.datasheet.DDGS --
there's no module-level binding in tools.datasheet to patch. Mirrors
tests/test_web_search.py, which covers the same pattern in
tools/web.py's web_search.
"""

import builtins
from unittest.mock import MagicMock, patch

import ddgs
import tools.datasheet as datasheet


def _ddgs_returning(results):
    """A fake DDGS context manager whose .text(...) returns `results`."""
    instance = MagicMock()
    instance.text.return_value = results
    instance.__enter__.return_value = instance
    instance.__exit__.return_value = False
    return MagicMock(return_value=instance)


def test_empty_query_is_rejected_without_calling_ddgs():
    with patch.object(ddgs, "DDGS", _ddgs_returning([])) as fake_ddgs:
        output = datasheet.find_datasheet("   ")

    assert "required" in output.lower()
    fake_ddgs.assert_not_called()


def test_pdf_results_are_prioritized_over_non_pdf_results():
    results = [
        {"title": "Product page", "href": "https://vendor.test/product"},
        {"title": "Datasheet PDF", "href": "https://vendor.test/ds.PDF"},
    ]
    with patch.object(ddgs, "DDGS", _ddgs_returning(results)):
        output = datasheet.find_datasheet("LM317")

    assert "PDF datasheet results" in output
    assert "Datasheet PDF" in output
    assert "Product page" not in output


def test_falls_back_to_all_results_when_no_pdf_link_present():
    results = [{"title": "Vendor page", "href": "https://vendor.test/info"}]
    with patch.object(ddgs, "DDGS", _ddgs_returning(results)):
        output = datasheet.find_datasheet("LM317")

    assert "No direct PDF links found" in output
    assert "Vendor page" in output


def test_no_results_returns_friendly_message():
    with patch.object(ddgs, "DDGS", _ddgs_returning([])):
        output = datasheet.find_datasheet("something obscure")

    assert "No datasheet results found" in output
    assert "something obscure" in output


def test_missing_ddgs_package_returns_friendly_message(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("no module named ddgs")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    output = datasheet.find_datasheet("LM317")

    assert "not installed" in output.lower()
    assert "pip install" in output.lower()


# --- retry behavior --------------------------------------------------------
# This is the actual regression coverage: find_datasheet used to have no
# retry at all -- a single dropped connection failed the whole search
# immediately, unlike every other network-touching tool.

def test_transient_failure_then_success_is_retried(monkeypatch):
    monkeypatch.setattr(datasheet.time, "sleep", lambda s: None)

    ok_instance = MagicMock()
    ok_instance.text.return_value = [
        {"title": "Recovered PDF", "href": "https://ok.test/ds.pdf"}
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
        output = datasheet.find_datasheet("LM317")

    assert "Recovered PDF" in output
    assert call_count["n"] == 2


def test_gives_up_after_configured_attempts_and_reports_last_error(monkeypatch):
    monkeypatch.setattr(datasheet.time, "sleep", lambda s: None)

    from config import CONFIG as real_config
    monkeypatch.setitem(real_config, "network_retry_attempts", 2)

    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise ConnectionError(f"still down (attempt {call_count['n']})")

    with patch.object(ddgs, "DDGS", side_effect=always_fails):
        output = datasheet.find_datasheet("LM317")

    assert "Datasheet search failed" in output
    assert call_count["n"] == 2


def test_does_not_retry_when_attempts_is_one(monkeypatch):
    monkeypatch.setattr(datasheet.time, "sleep", lambda s: None)

    from config import CONFIG as real_config
    with patch.dict(real_config, {"network_retry_attempts": 1}):
        call_count = {"n": 0}

        def always_fails():
            call_count["n"] += 1
            raise ConnectionError("down")

        with patch.object(ddgs, "DDGS", side_effect=always_fails):
            datasheet.find_datasheet("LM317")

        assert call_count["n"] == 1
