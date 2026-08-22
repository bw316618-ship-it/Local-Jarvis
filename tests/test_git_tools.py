"""Tests for tools/git_tools.py.

These run against real, throwaway git repositories created under
tmp_path -- not mocked subprocess calls. git_tools.py is thin plumbing
over the `git` CLI, so a mock would mostly just test that we call
subprocess.run with certain arguments, without verifying the arguments
are actually correct git usage or that output parsing (or lack thereof)
holds up against real git output. This had zero test coverage before,
despite four of its eight tools being confirmation-gated (git_add,
git_commit, git_checkout, git_push) and it being load-bearing for
CODING mode.
"""

from unittest.mock import MagicMock

import pytest

from brain.llm import JarvisLLM
from brain.mode_config import CODING
from tools.git_tools import (
    GIT_RISKY_TOOLS,
    GIT_TOOL_FUNCTIONS,
    git_add,
    git_branch_list,
    git_checkout,
    git_commit,
    git_diff,
    git_log,
    git_push,
    git_status,
)
from voice import session_state


def setup_function():
    session_state.set_mode(session_state.NORMAL)


def teardown_function():
    session_state.set_mode(session_state.NORMAL)


def _init_repo(path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)


def _commit_all(path, message):
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(path), check=True)


# --- read-only ops against a real repo -----------------------------------

def test_git_status_reports_untracked_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    result = git_status(str(tmp_path))
    assert "a.txt" in result


def test_git_status_on_non_repo_reports_not_a_repo(tmp_path):
    result = git_status(str(tmp_path))
    assert "not a git repository" in result.lower()


def test_git_status_on_nonexistent_path():
    result = git_status("/definitely/not/a/real/path/anywhere")
    assert "does not exist" in result


def test_git_log_shows_real_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    _commit_all(tmp_path, "initial commit")
    result = git_log(str(tmp_path))
    assert "initial commit" in result


def test_git_log_respects_count(tmp_path):
    _init_repo(tmp_path)
    for i in range(5):
        (tmp_path / "f.txt").write_text(str(i))
        _commit_all(tmp_path, f"commit {i}")
    result = git_log(str(tmp_path), count=2)
    assert "commit 4" in result
    assert "commit 3" in result
    assert "commit 0" not in result


def test_git_diff_shows_uncommitted_change(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("line one\n")
    _commit_all(tmp_path, "initial")
    (tmp_path / "a.txt").write_text("line one\nline two\n")
    result = git_diff(str(tmp_path))
    assert "line two" in result


def test_git_diff_staged_only_shows_staged_changes(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("line one\n")
    _commit_all(tmp_path, "initial")
    (tmp_path / "a.txt").write_text("line one\nline two\n")
    # Not staged -- diff --staged should be empty.
    result = git_diff(str(tmp_path), staged=True)
    assert "line two" not in result


def test_git_branch_list_marks_current_branch(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    _commit_all(tmp_path, "initial")
    result = git_branch_list(str(tmp_path))
    assert "*" in result  # current branch marker


# --- state-changing ops against a real repo -------------------------------

def test_git_add_actually_stages_the_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    git_add(str(tmp_path), "a.txt")
    status = git_status(str(tmp_path))
    assert "Changes to be committed" in status or "new file" in status.lower()


def test_git_commit_actually_creates_a_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    git_add(str(tmp_path), "a.txt")
    git_commit(str(tmp_path), "my real commit message")
    log = git_log(str(tmp_path))
    assert "my real commit message" in log


def test_git_commit_without_message_is_rejected_before_touching_git():
    result = git_commit(".", "")
    assert "required" in result.lower()


def test_git_checkout_actually_switches_branch(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    _commit_all(tmp_path, "initial")
    import subprocess
    subprocess.run(["git", "branch", "feature-x"], cwd=str(tmp_path), check=True)

    git_checkout(str(tmp_path), "feature-x")
    status = git_status(str(tmp_path))
    assert "feature-x" in status


def test_git_checkout_without_branch_is_rejected():
    result = git_checkout(".", "")
    assert "required" in result.lower()


def test_git_push_actually_pushes_to_a_real_local_remote(tmp_path):
    """The only one of these worth being paranoid about: push a real
    commit from a real working repo to a real (local, bare) remote, and
    verify the remote's ref actually advanced -- not just that git_push
    returned without an error string."""
    import subprocess

    bare_remote = tmp_path / "remote.git"
    bare_remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare"], cwd=str(bare_remote), check=True)

    work = tmp_path / "work"
    work.mkdir()
    _init_repo(work)
    (work / "a.txt").write_text("hello")
    _commit_all(work, "initial commit")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare_remote)], cwd=str(work), check=True
    )
    subprocess.run(
        ["git", "branch", "-M", "main"], cwd=str(work), check=True
    )

    result = git_push(str(work), remote="origin", branch="main")
    assert "error" not in result.lower() and "rejected" not in result.lower()

    # Verify against the bare remote directly -- not just trusting git_push's
    # own success message.
    log_on_remote = subprocess.run(
        ["git", "log", "--oneline", "main"],
        cwd=str(bare_remote), capture_output=True, text=True,
    )
    assert "initial commit" in log_on_remote.stdout or log_on_remote.returncode == 0


def test_git_push_to_unreachable_remote_reports_failure_not_a_crash(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    _commit_all(tmp_path, "initial")
    result = git_push(str(tmp_path), remote="origin", branch="main")
    # No 'origin' remote configured at all -- git itself should report
    # this cleanly, and the tool should surface it, not raise.
    assert isinstance(result, str)
    assert result.strip() != ""


# --- risky gating -----------------------------------------------------

def test_state_changing_ops_are_risky_read_only_ops_are_not():
    assert GIT_RISKY_TOOLS == {"git_add", "git_commit", "git_checkout", "git_push"}
    for name in ("git_status", "git_log", "git_diff", "git_branch_list"):
        assert name not in GIT_RISKY_TOOLS


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK"
    jarvis.companion_system_prompt = "COMPANION"
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


def test_git_commit_asks_for_confirmation_through_run_tool_call(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    git_add(str(tmp_path), "a.txt")

    jarvis = make_jarvis()
    session_state.set_mode(CODING)
    confirmations = []
    jarvis.confirm_callback = lambda name, args: confirmations.append(name) or False

    result = jarvis._run_tool_call(
        {
            "function": {
                "name": "git_commit",
                "arguments": {"repo_path": str(tmp_path), "message": "should be blocked"},
            }
        }
    )

    assert confirmations == ["git_commit"]
    assert "declined" in result.lower()
    log = git_log(str(tmp_path))
    assert "should be blocked" not in log


def test_git_status_runs_without_confirmation_through_run_tool_call(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")

    jarvis = make_jarvis()
    session_state.set_mode(CODING)
    confirmations = []
    jarvis.confirm_callback = lambda name, args: confirmations.append(name) or True

    result = jarvis._run_tool_call(
        {"function": {"name": "git_status", "arguments": {"repo_path": str(tmp_path)}}}
    )

    assert confirmations == []
    assert "a.txt" in result


# --- error handling ----------------------------------------------------

def test_invalid_path_does_not_raise():
    result = git_status("\x00invalid")
    assert isinstance(result, str)


def test_all_functions_registered():
    for name in GIT_TOOL_FUNCTIONS:
        assert callable(GIT_TOOL_FUNCTIONS[name])
