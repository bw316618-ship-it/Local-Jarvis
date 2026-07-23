"""Insights: repeated-failure detection, repeated-action detection (scoped
to meaningful tools only), lookback window, and folder growth tracking."""

import json
from datetime import datetime, timedelta, timezone

import memory.insights as ins


def _entry(tool, args, result, days_ago=0):
    return {
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
        "tool": tool,
        "arguments": args,
        "risky": False,
        "approved": None,
        "result_preview": result,
    }


def _write_log(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_repeated_failure_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "LOG_PATH", tmp_path / "audit_log.jsonl")
    entries = [_entry("run_command", {"command": "python app.py"}, "Command timed out after 30 seconds.", d) for d in (1, 2, 3, 4)]
    _write_log(ins.LOG_PATH, entries)

    suggestions = ins.get_suggestions(include_folder_check=False)
    assert any("run_command" in s and "4 times" in s for s in suggestions)


def test_repeated_action_is_detected_for_worthy_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "LOG_PATH", tmp_path / "audit_log.jsonl")
    entries = [_entry("search_files", {"query": "flask project"}, "Matching files:\n- x.py", d) for d in (1, 3, 5)]
    _write_log(ins.LOG_PATH, entries)

    suggestions = ins.get_suggestions(include_folder_check=False)
    assert any("search_files" in s and "3 times" in s for s in suggestions)


def test_trivial_tools_are_never_flagged_even_when_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "LOG_PATH", tmp_path / "audit_log.jsonl")
    entries = [_entry("calculate", {"expression": "2+2"}, "4", d) for d in (1, 2, 3)]
    _write_log(ins.LOG_PATH, entries)

    suggestions = ins.get_suggestions(include_folder_check=False)
    assert not any("calculate" in s for s in suggestions)


def test_entries_outside_lookback_window_are_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "LOG_PATH", tmp_path / "audit_log.jsonl")
    entries = [_entry("run_command", {"command": "old"}, "Error: x", d) for d in (30, 31, 32)]
    _write_log(ins.LOG_PATH, entries)

    suggestions = ins.get_suggestions(include_folder_check=False)
    assert not any("old" in s for s in suggestions)


def test_below_threshold_count_does_not_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "LOG_PATH", tmp_path / "audit_log.jsonl")
    entries = [_entry("git_status", {"repo_path": "."}, "clean", d) for d in (1, 2)]
    _write_log(ins.LOG_PATH, entries)

    suggestions = ins.get_suggestions(include_folder_check=False)
    assert not any("git_status" in s for s in suggestions)


def test_folder_growth_baseline_then_detects_growth(tmp_path, monkeypatch):
    tracked = tmp_path / "Documents"
    tracked.mkdir()
    monkeypatch.setattr(ins, "SIZE_SNAPSHOT_PATH", tmp_path / "snapshot.json")

    import config
    monkeypatch.setitem(config.CONFIG, "index_roots", [str(tracked)])

    # Mock the size measurement directly rather than writing hundreds of MB
    # of real test data to disk -- this test is about the threshold/
    # comparison logic, not actual filesystem I/O performance.
    sizes = iter([10.0, 610.0, 610.0])  # MB: baseline, +600MB growth, stable
    monkeypatch.setattr(ins, "_folder_size_mb", lambda path: next(sizes))

    assert ins._check_folder_growth() == [], "first-ever check should establish a baseline, not suggest anything"

    suggestions = ins._check_folder_growth()
    assert len(suggestions) == 1
    assert "Documents" in suggestions[0]

    # stable size afterward should not re-trigger
    assert ins._check_folder_growth() == []
