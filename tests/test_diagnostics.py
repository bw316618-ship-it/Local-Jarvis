"""Diagnostics: these run against the real psutil, not mocks -- system
stats are genuinely cross-platform testable, unlike the Windows/macOS-only
tools elsewhere in the suite."""

from tools.diagnostics import system_status, top_processes


def test_system_status_returns_all_expected_fields():
    result = system_status()
    assert "CPU:" in result
    assert "Memory:" in result
    assert "Disk:" in result
    assert "Uptime:" in result
    assert "Running processes:" in result


def test_top_processes_defaults_to_memory():
    result = top_processes()
    assert "memory %" in result


def test_top_processes_respects_count():
    result = top_processes(count=2)
    # 1 header line + up to `count` process lines
    process_lines = [line for line in result.splitlines() if line.startswith("-")]
    assert len(process_lines) <= 2


def test_top_processes_invalid_sort_key_defaults_to_memory():
    result = top_processes(by="bogus")
    assert "memory %" in result


def test_top_processes_cpu_mode():
    result = top_processes(by="cpu", count=3)
    assert "CPU %" in result
