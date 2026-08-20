"""Tests for CODING mode.

Covers tools/coding_tools.py's functions directly (real subprocess calls
against temp files -- not mocked, since these are thin wrappers around
`python -m pytest` / `python <file>` and a mock would just test the mock),
CODING mode's wiring into brain/mode_config.py, and the derived subprocess
timeout that keeps run_tests/run_python_file from being silently orphaned
by brain/llm.py's outer per-tool-call timeout (see coding_tools.py's
module docstring for why that matters).
"""

from unittest.mock import MagicMock

import pytest

from brain.llm import JarvisLLM
from brain.mode_config import CODING, COMPANION, CREATIVE, NORMAL, get_mode_config
from config import CONFIG
from tools.coding_tools import (
    CODING_RISKY_TOOLS,
    CODING_TOOL_FUNCTIONS,
    SUBPROCESS_TIMEOUT_SECONDS,
    lint_python,
    run_python_file,
    run_tests,
    search_code,
)
from voice import session_state


def setup_function():
    session_state.set_mode(NORMAL)


def teardown_function():
    session_state.set_mode(NORMAL)


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK"
    jarvis.companion_system_prompt = "COMPANION"
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


# --- run_tests -------------------------------------------------------------

def test_run_tests_reports_a_passing_suite(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    result = run_tests(str(tmp_path))
    assert "1 passed" in result


def test_run_tests_reports_a_failing_suite(tmp_path):
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    result = run_tests(str(tmp_path))
    assert "1 failed" in result


def test_run_tests_respects_pattern_filter(tmp_path):
    (tmp_path / "test_two.py").write_text(
        "def test_alpha():\n    assert True\n\n"
        "def test_beta():\n    assert False\n"
    )
    result = run_tests(str(tmp_path), pattern="alpha")
    assert "1 passed" in result
    assert "failed" not in result


def test_run_tests_rejects_nonexistent_path():
    result = run_tests("/definitely/not/a/real/path/anywhere")
    assert "does not exist" in result


# --- run_python_file ---------------------------------------------------

def test_run_python_file_captures_stdout_and_exit_code(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hi from script')\n")
    result = run_python_file(str(script))
    assert "Exit code 0" in result
    assert "hi from script" in result


def test_run_python_file_reports_nonzero_exit_code(tmp_path):
    script = tmp_path / "fails.py"
    script.write_text("import sys\nsys.exit(3)\n")
    result = run_python_file(str(script))
    assert "Exit code 3" in result


def test_run_python_file_passes_through_args(tmp_path):
    script = tmp_path / "echoargs.py"
    script.write_text("import sys\nprint(sys.argv[1:])\n")
    result = run_python_file(str(script), args="foo bar")
    assert "'foo', 'bar'" in result


def test_run_python_file_rejects_a_directory(tmp_path):
    result = run_python_file(str(tmp_path))
    assert "directory" in result.lower()


# --- lint_python (ast.parse only -- never executes) --------------------

def test_lint_python_reports_clean_file(tmp_path):
    (tmp_path / "clean.py").write_text("def f():\n    return 1\n")
    result = lint_python(str(tmp_path))
    assert "No syntax errors" in result


def test_lint_python_reports_syntax_error_with_line_number(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n    return 1\n")
    result = lint_python(str(tmp_path))
    assert "broken.py" in result
    assert "syntax error" in result.lower() or "syntax errors" in result.lower()


def test_lint_python_never_executes_the_file(tmp_path):
    """A file that would raise or have side effects if executed should
    still lint cleanly, since ast.parse only parses -- proves this isn't
    secretly shelling out to `python -c` or similar."""
    (tmp_path / "would_explode.py").write_text(
        "raise RuntimeError('this must never actually run')\n"
    )
    result = lint_python(str(tmp_path))
    assert "No syntax errors" in result


# --- search_code (read-only) --------------------------------------------

def test_search_code_finds_matches_with_file_and_line(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nTODO_MARKER = True\ny = 2\n")
    result = search_code("TODO_MARKER", str(tmp_path))
    assert "a.py:2" in result
    assert "TODO_MARKER" in result


def test_search_code_is_case_insensitive(tmp_path):
    (tmp_path / "a.py").write_text("needle_value = 1\n")
    result = search_code("NEEDLE_VALUE", str(tmp_path))
    assert "a.py:1" in result


def test_search_code_respects_file_glob(tmp_path):
    (tmp_path / "match.py").write_text("marker_x = 1\n")
    (tmp_path / "skip.txt").write_text("marker_x = 1\n")
    result = search_code("marker_x", str(tmp_path), file_glob="*.py")
    assert "match.py" in result
    assert "skip.txt" not in result


def test_search_code_reports_no_matches(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    result = search_code("nothing_like_this_exists_here", str(tmp_path))
    assert "No matches" in result


def test_search_code_requires_a_query():
    result = search_code("", ".")
    assert "required" in result.lower()


# --- risky gating --------------------------------------------------------

def test_execution_tools_are_risky_readonly_tools_are_not():
    assert "run_tests" in CODING_RISKY_TOOLS
    assert "run_python_file" in CODING_RISKY_TOOLS
    assert "lint_python" not in CODING_RISKY_TOOLS
    assert "search_code" not in CODING_RISKY_TOOLS


def test_run_tests_asks_for_confirmation_through_run_tool_call(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    jarvis = make_jarvis()
    session_state.set_mode(CODING)
    confirmations = []
    jarvis.confirm_callback = lambda name, args: confirmations.append(name) or False

    result = jarvis._run_tool_call(
        {"function": {"name": "run_tests", "arguments": {"path": str(tmp_path)}}}
    )

    assert confirmations == ["run_tests"]
    assert "declined" in result.lower()


def test_search_code_runs_without_confirmation_through_run_tool_call(tmp_path):
    (tmp_path / "a.py").write_text("needle = 1\n")

    jarvis = make_jarvis()
    session_state.set_mode(CODING)
    confirmations = []
    jarvis.confirm_callback = lambda name, args: confirmations.append(name) or True

    result = jarvis._run_tool_call(
        {"function": {"name": "search_code", "arguments": {"query": "needle", "path": str(tmp_path)}}}
    )

    assert confirmations == []  # never asked -- not risky
    assert "a.py" in result


# --- timeout derivation --------------------------------------------------

def test_subprocess_timeout_is_derived_below_the_outer_tool_call_ceiling():
    """coding_tools.py's own subprocess timeout must fire before
    brain/llm.py's outer per-tool-call Future.result(timeout=...) does --
    otherwise the outer wrapper reports 'timed out' while the subprocess
    keeps running in the background thread, unbounded by anything this
    module controls. See coding_tools.py's module docstring."""
    assert SUBPROCESS_TIMEOUT_SECONDS < CONFIG["tool_call_timeout_seconds"]
    assert SUBPROCESS_TIMEOUT_SECONDS >= 5


# --- mode wiring -----------------------------------------------------------

def test_coding_mode_is_a_valid_mode():
    session_state.set_mode(CODING)
    assert session_state.current_mode() == CODING


def test_coding_registry_contains_git_file_and_coding_tools():
    jarvis = make_jarvis()
    session_state.set_mode(CODING)
    registry, risky = jarvis._tool_registry_for_mode(CODING)

    for name in CODING_TOOL_FUNCTIONS:
        assert name in registry
    assert "git_status" in registry
    assert "git_commit" in registry
    assert "read_file" in registry
    assert "git_commit" in risky
    assert "run_tests" in risky


@pytest.mark.parametrize("other_mode", [NORMAL, COMPANION, CREATIVE])
def test_coding_only_tools_absent_from_other_modes(other_mode):
    jarvis = make_jarvis()
    session_state.set_mode(other_mode)
    registry, _ = jarvis._tool_registry_for_mode(other_mode)
    assert "run_tests" not in registry
    assert "run_python_file" not in registry
    assert "lint_python" not in registry
    assert "search_code" not in registry


def test_coding_mode_uses_coding_prompt_and_enables_planning(monkeypatch):
    import brain.llm as llm_module

    jarvis = make_jarvis()
    captured = []

    def fake_stream(messages, tools, on_token=None, on_sentence=None):
        captured.append((messages[0]["content"], tools))
        return "ok", None

    jarvis._stream_round = fake_stream
    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda *a, **k: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda *a, **k: [])
    monkeypatch.setattr(
        llm_module, "get_embedder", lambda: MagicMock(encode=lambda q: MagicMock(tolist=lambda: [0.0]))
    )
    plan_calls = []
    monkeypatch.setattr(JarvisLLM, "_make_plan", lambda self, msg: plan_calls.append(msg) or "no plan needed")

    session_state.set_mode(CODING)
    jarvis.chat(
        "add a function, then write a test for it, then run the tests",
        on_step=lambda m: None,
    )

    prompt_used, tools_used = captured[0]
    assert prompt_used == get_mode_config(CODING)["prompt"]
    assert plan_calls, "CODING mode should attempt planning for a multi-step request"
