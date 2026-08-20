"""
Coding tools for Jarvis's CODING mode.

Mirrors tools/git_tools.py's design on purpose: operate on any path (no
workspace/ sandbox, since a codebase you're working in usually isn't
inside Jarvis's own workspace/ folder), a subprocess timeout, and
captured stdout+stderr over blind execution.

A subtlety worth knowing if you touch this file: every tool call, this
one included, is wrapped by brain/llm.py's _run_tool_call in a hard
CONFIG["tool_call_timeout_seconds"] ceiling via
concurrent.futures.Future.result(timeout=...). That wrapper does NOT
kill the underlying thread or subprocess when it fires -- it just stops
waiting and reports a timeout string back to the model, while the
subprocess keeps running in the background until its own timeout (or
completion). So run_tests/run_python_file's own subprocess timeout is
deliberately set a few seconds BELOW the outer ceiling, computed from
CONFIG at import time, so the inner timeout fires first and the string
we return actually reflects reality. If you have a slow test suite and
need more headroom, raise tool_call_timeout_seconds in
jarvis_config.json rather than editing SUBPROCESS_TIMEOUT_SECONDS here
directly -- this module's timeout is derived from it precisely so the
two can't drift out of sync.
"""

import ast
import fnmatch
import subprocess
import sys
from pathlib import Path

from config import CONFIG

_OUTER_TIMEOUT_SECONDS = CONFIG["tool_call_timeout_seconds"]
SUBPROCESS_TIMEOUT_SECONDS = max(5, _OUTER_TIMEOUT_SECONDS - 5)

MAX_OUTPUT_CHARS = 6000
MAX_SEARCH_MATCHES = 40

# Directories never worth walking into for lint/search -- version control
# internals, virtualenvs, and caches produce noise or, in the case of
# .git, can be enormous.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache"}


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    remaining = len(text) - MAX_OUTPUT_CHARS
    return text[:MAX_OUTPUT_CHARS] + f"\n[... truncated, {remaining} more characters ...]"


def _resolve_existing(path: str) -> tuple[Path, str]:
    """Resolve a path, returning (resolved_path, error_message). Exactly
    one of the two is meaningful -- error_message is empty on success."""
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as e:
        return None, f"Invalid path '{path}': {e}"
    if not resolved.exists():
        return None, f"'{path}' does not exist."
    return resolved, ""


def _iter_python_files(root: Path):
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for p in root.rglob("*.py"):
        if not any(part in _SKIP_DIRS for part in p.parts):
            yield p


def run_tests(path: str = ".", pattern: str = "") -> str:
    """Run pytest against a path (file, folder, or a single test node like
    tests/test_x.py::test_y), optionally filtered with -k pattern."""
    resolved, error = _resolve_existing(path)
    if error:
        return error

    args = [sys.executable, "-m", "pytest", str(resolved), "-q"]
    if pattern.strip():
        args += ["-k", pattern]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"Test run timed out after {SUBPROCESS_TIMEOUT_SECONDS}s."
    except Exception as e:
        return f"Could not run tests: {e}"

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return _truncate(output) if output else "(pytest produced no output)"


def run_python_file(path: str, args: str = "") -> str:
    """Run a Python script and capture its output. `args` is a
    space-separated string of command-line arguments to pass it."""
    resolved, error = _resolve_existing(path)
    if error:
        return error
    if resolved.is_dir():
        return f"'{path}' is a directory, not a script."

    arg_list = args.split() if args.strip() else []

    try:
        result = subprocess.run(
            [sys.executable, str(resolved)] + arg_list,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"Script timed out after {SUBPROCESS_TIMEOUT_SECONDS}s."
    except Exception as e:
        return f"Could not run '{path}': {e}"

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    prefix = f"Exit code {result.returncode}.\n"
    return prefix + (_truncate(output) if output else "(no output)")


def lint_python(path: str = ".") -> str:
    """Check Python file(s) for syntax errors by parsing them (does not
    execute any code, only parses it -- safe to run without confirmation)."""
    resolved, error = _resolve_existing(path)
    if error:
        return error

    files = list(_iter_python_files(resolved))
    if not files:
        return f"No .py files found under '{path}'."

    problems = []
    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=str(f))
        except SyntaxError as e:
            problems.append(f"{f}:{e.lineno}: {e.msg}")
        except Exception as e:
            problems.append(f"{f}: could not read/parse ({e})")

    if not problems:
        return f"No syntax errors in {len(files)} file(s) under '{path}'."

    summary = f"{len(problems)} of {len(files)} file(s) have syntax errors:\n"
    return _truncate(summary + "\n".join(problems))


def search_code(query: str, path: str = ".", file_glob: str = "*.py") -> str:
    """Search for a literal substring across files under path matching
    file_glob (default *.py). Plain substring match, case-insensitive --
    not a regex, so there's no ReDoS surface from a model-supplied pattern."""
    resolved, error = _resolve_existing(path)
    if error:
        return error
    if not query.strip():
        return "A search query is required."

    needle = query.lower()
    matches = []

    if resolved.is_file():
        candidates = [resolved] if fnmatch.fnmatch(resolved.name, file_glob) else []
    else:
        candidates = [
            p for p in resolved.rglob("*")
            if p.is_file()
            and fnmatch.fnmatch(p.name, file_glob)
            and not any(part in _SKIP_DIRS for part in p.parts)
        ]

    for f in sorted(candidates):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if needle in line.lower():
                matches.append(f"{f}:{i}: {line.strip()}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    break
        if len(matches) >= MAX_SEARCH_MATCHES:
            break

    if not matches:
        return f"No matches for '{query}' under '{path}' (glob: {file_glob})."

    suffix = f"\n[... stopped at {MAX_SEARCH_MATCHES} matches ...]" if len(matches) >= MAX_SEARCH_MATCHES else ""
    return "\n".join(matches) + suffix


CODING_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run pytest against a path (file, folder, or a specific test node) "
                "and return the output. Executes code in the target project -- "
                "confirmation is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File, folder, or test node to run. Defaults to '.'."},
                    "pattern": {"type": "string", "description": "Optional -k filter expression."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_file",
            "description": (
                "Run a Python script and return its output and exit code. "
                "Executes arbitrary code from the target file -- confirmation is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the .py file to run."},
                    "args": {"type": "string", "description": "Space-separated command-line arguments."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lint_python",
            "description": (
                "Check Python file(s) under a path for syntax errors. Only parses, "
                "never executes -- runs automatically without confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or folder to check. Defaults to '.'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search for a literal substring across files under a path (default *.py). "
                "Read-only -- runs automatically without confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for."},
                    "path": {"type": "string", "description": "File or folder to search under. Defaults to '.'."},
                    "file_glob": {"type": "string", "description": "Filename glob to match. Defaults to '*.py'."},
                },
                "required": ["query"],
            },
        },
    },
]

CODING_TOOL_FUNCTIONS = {
    "run_tests": run_tests,
    "run_python_file": run_python_file,
    "lint_python": lint_python,
    "search_code": search_code,
}

# run_tests/run_python_file execute code from the target project -- same
# bar as git_commit/git_push in tools/git_tools.py. lint_python only
# parses (ast.parse never executes module-level code) and search_code
# only reads, so neither needs confirmation.
CODING_RISKY_TOOLS = {"run_tests", "run_python_file"}
