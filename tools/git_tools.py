"""
Git integration for Jarvis -- structured tools for repo status, history,
and common actions, rather than relying on the generic run_command tool
and hoping the model gets the right git incantation.

Read-only operations (status, log, diff, branch listing) run automatically.
Anything that changes repo state -- staging, committing, switching
branches, pushing -- is registered as risky and asks for confirmation
first, since git mistakes (a bad commit, a push to the wrong branch) are
often more annoying to undo than a file operation.
"""

import subprocess
from pathlib import Path

TIMEOUT_SECONDS = 30


def _run_git(args, repo_path="."):
    try:
        repo = Path(repo_path).expanduser().resolve()
    except Exception as e:
        return f"Invalid repo path '{repo_path}': {e}"

    if not repo.exists():
        return f"'{repo_path}' does not exist."

    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return "Git is not installed, or not on PATH."
    except subprocess.TimeoutExpired:
        return f"Git command timed out after {TIMEOUT_SECONDS} seconds."
    except Exception as e:
        return f"Git command failed: {e}"

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return output if output else "(no output)"


def git_status(repo_path: str = ".") -> str:
    """Show working tree status: branch, staged/unstaged/untracked files."""
    return _run_git(["status"], repo_path)


def git_log(repo_path: str = ".", count: int = 10) -> str:
    """Show recent commit history, one line per commit."""
    return _run_git(["log", f"-{max(1, count)}", "--oneline", "--decorate"], repo_path)


def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """Show uncommitted changes (or staged changes if staged=True)."""
    args = ["diff"] + (["--staged"] if staged else [])
    return _run_git(args, repo_path)


def git_branch_list(repo_path: str = ".") -> str:
    """List local branches, with the current one marked and tracking info."""
    return _run_git(["branch", "-vv"], repo_path)


def git_add(repo_path: str = ".", files: str = ".") -> str:
    """Stage files for commit. `files` is a space-separated list, or '.' for everything."""
    file_list = files.split() if files.strip() else ["."]
    return _run_git(["add"] + file_list, repo_path)


def git_commit(repo_path: str = ".", message: str = "") -> str:
    """Commit currently staged changes with the given message."""
    if not message.strip():
        return "A commit message is required."
    return _run_git(["commit", "-m", message], repo_path)


def git_checkout(repo_path: str = ".", branch: str = "") -> str:
    """Switch to an existing branch (or create it with -b semantics via git_checkout_new)."""
    if not branch.strip():
        return "A branch name is required."
    return _run_git(["checkout", branch], repo_path)


def git_push(repo_path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push commits to a remote. `branch` defaults to the current branch if omitted."""
    args = ["push", remote]
    if branch.strip():
        args.append(branch)
    return _run_git(args, repo_path)


GIT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show git working tree status (branch, staged/unstaged/untracked files) for a repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show recent commit history for a repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "count": {"type": "integer", "description": "How many commits to show. Defaults to 10."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show uncommitted (or staged) changes in a repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "staged": {"type": "boolean", "description": "Show staged changes instead of unstaged. Defaults to false."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch_list",
            "description": "List local branches in a repo, with the current one marked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_add",
            "description": "Stage files in a repo for the next commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "files": {"type": "string", "description": "Space-separated file paths, or '.' for everything. Defaults to '.'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit currently staged changes in a repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "message": {"type": "string", "description": "The commit message."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_checkout",
            "description": "Switch to an existing branch in a repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "branch": {"type": "string", "description": "Branch name to switch to."},
                },
                "required": ["branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_push",
            "description": "Push committed changes to a remote.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to the current directory."},
                    "remote": {"type": "string", "description": "Remote name. Defaults to 'origin'."},
                    "branch": {"type": "string", "description": "Branch to push. Defaults to the current branch."},
                },
                "required": [],
            },
        },
    },
]

GIT_TOOL_FUNCTIONS = {
    "git_status": git_status,
    "git_log": git_log,
    "git_diff": git_diff,
    "git_branch_list": git_branch_list,
    "git_add": git_add,
    "git_commit": git_commit,
    "git_checkout": git_checkout,
    "git_push": git_push,
}

# Read-only ops (status/log/diff/branch_list) are safe. Anything that
# changes repo state asks for confirmation first.
GIT_RISKY_TOOLS = {"git_add", "git_commit", "git_checkout", "git_push"}
