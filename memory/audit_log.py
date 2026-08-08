"""
Audit logging for Jarvis -- every tool call gets a record of what was
run, when, and whether it required (and received) confirmation.

Stored as JSON Lines (one JSON object per line) in memory/audit_log.jsonl,
so it's easy to tail, grep, or load one line at a time without parsing a
single giant JSON document. Logging failures are swallowed rather than
raised -- a broken log should never take down an actual tool call.

Arguments are previewed/truncated the same way results already were --
`write_file` content, `run_command` strings, `remember_fact` payloads,
git commit messages, etc. could otherwise end up sitting in plaintext in
this file indefinitely, well beyond what's useful for an audit trail.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "memory" / "audit_log.jsonl"

MAX_RESULT_PREVIEW = 200
MAX_ARG_PREVIEW = 200


def _preview_arguments(arguments: dict) -> dict:
    """Truncate each argument value to MAX_ARG_PREVIEW chars, mirroring how
    result_preview already handles tool results -- keeps the log useful
    for debugging/insights without storing full file contents, commands,
    or remembered facts in plaintext forever."""
    previewed = {}
    for key, value in (arguments or {}).items():
        text = str(value)
        if len(text) > MAX_ARG_PREVIEW:
            remaining = len(text) - MAX_ARG_PREVIEW
            text = text[:MAX_ARG_PREVIEW] + f"...[{remaining} more chars]"
        previewed[key] = text
    return previewed


def log_tool_call(name: str, arguments: dict, risky: bool, approved, result: str) -> None:
    """Append one record of a tool call to the audit log.

    `approved` is True/False for risky calls that went through
    confirmation, or None for calls that didn't need confirmation at all
    -- so the log can tell "wasn't risky" apart from "was risky and got
    approved".
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": name,
        "arguments": _preview_arguments(arguments),
        "risky": risky,
        "approved": approved,
        "result_preview": (result or "")[:MAX_RESULT_PREVIEW],
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def read_recent(n: int = 20) -> str:
    """Return a human-readable summary of the last `n` audit log entries."""
    if not LOG_PATH.exists():
        return "No tool calls have been logged yet."

    try:
        lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    except Exception as e:
        return f"Could not read the audit log: {e}"

    if not lines:
        return "No tool calls have been logged yet."

    formatted = []
    for line in lines[-n:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not entry.get("risky"):
            status = "auto"
        else:
            status = "approved" if entry.get("approved") else "declined"

        # Defensive .get() throughout -- a schema-incomplete but still
        # JSON-valid line (partial write, future field rename) shouldn't
        # be able to raise a KeyError here and take down the caller (e.g.
        # main.py's /log command has no try/except around this call).
        timestamp = entry.get("timestamp", "?")
        tool = entry.get("tool", "?")
        tool_args = entry.get("arguments", {})
        formatted.append(f"[{timestamp}] {tool}({tool_args}) -- {status}")

    return "\n".join(formatted) if formatted else "No valid log entries found."
