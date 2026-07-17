"""
Audit logging for Jarvis -- every tool call gets a record of what was
run, when, and whether it required (and received) confirmation.

Stored as JSON Lines (one JSON object per line) in memory/audit_log.jsonl,
so it's easy to tail, grep, or load one line at a time without parsing a
single giant JSON document. Logging failures are swallowed rather than
raised -- a broken log should never take down an actual tool call.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "memory" / "audit_log.jsonl"

MAX_RESULT_PREVIEW = 200


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
        "arguments": arguments,
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

        formatted.append(f"[{entry['timestamp']}] {entry['tool']}({entry['arguments']}) -- {status}")

    return "\n".join(formatted) if formatted else "No valid log entries found."
