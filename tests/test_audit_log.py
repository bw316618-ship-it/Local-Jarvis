"""Audit log: argument truncation, defensive reading of malformed
entries, and log trimming once it grows past the retention cap."""

import json

import memory.audit_log as audit_log


def _read_lines(path):
    return path.read_text(encoding="utf-8").strip().splitlines()


def test_long_argument_values_are_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")

    long_content = "x" * 5000
    audit_log.log_tool_call(
        "write_file", {"path": "a.txt", "content": long_content}, risky=False, approved=None, result="ok"
    )

    entry = json.loads(_read_lines(audit_log.LOG_PATH)[0])
    stored = entry["arguments"]["content"]
    assert len(stored) < len(long_content)
    assert stored.startswith("x" * audit_log.MAX_ARG_PREVIEW)
    assert "more chars" in stored


def test_short_argument_values_are_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")

    audit_log.log_tool_call("calculate", {"expression": "2+2"}, risky=False, approved=None, result="4")

    entry = json.loads(_read_lines(audit_log.LOG_PATH)[0])
    assert entry["arguments"]["expression"] == "2+2"


def test_read_recent_tolerates_a_schema_incomplete_line(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")
    # Valid JSON, but missing "tool"/"timestamp"/"arguments" -- read_recent
    # previously indexed these with entry[...] instead of entry.get(...),
    # which would raise KeyError here and take down the caller (main.py's
    # /log command has no try/except around read_recent()).
    audit_log.LOG_PATH.write_text(json.dumps({"risky": False}) + "\n")

    result = audit_log.read_recent()

    assert "Traceback" not in result
    assert "?" in result


def test_log_is_trimmed_once_it_exceeds_the_retention_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "MAX_LOG_LINES", 10)
    # Force the cheap size pre-check to always trigger the full trim path,
    # deterministically, regardless of how small the test's own entries are.
    monkeypatch.setattr(audit_log, "_TRIM_CHECK_SIZE_BYTES", 1)

    for i in range(15):
        audit_log.log_tool_call("get_current_time", {}, risky=False, approved=None, result=str(i))

    lines = _read_lines(audit_log.LOG_PATH)
    assert len(lines) == 10, "log should be trimmed down to MAX_LOG_LINES"
    last_entry = json.loads(lines[-1])
    assert last_entry["result_preview"] == "14", "trimming should keep the most recent entries, not the oldest"


def test_log_is_not_trimmed_while_under_the_size_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "MAX_LOG_LINES", 10)
    # Default-sized threshold -- a handful of short entries should never
    # come close to it, so no trim should happen.

    for i in range(15):
        audit_log.log_tool_call("get_current_time", {}, risky=False, approved=None, result=str(i))

    assert len(_read_lines(audit_log.LOG_PATH)) == 15
