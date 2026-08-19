"""
File management tools for Jarvis.

All read/write/delete operations are sandboxed to a single `workspace/`
directory at the project root.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

MAX_READ_CHARS = 8000


def _safe_path(path: str) -> Path:
    """Resolve any supplied path inside WORKSPACE_DIR."""
    raw = str(path)

    if raw.startswith(("/", "\\")):
        raw = raw.lstrip("/\\")
    elif re.match(r"^[A-Za-z]:[\\/]", raw):
        raw = raw[2:].lstrip("/\\")

    candidate = Path(raw)
    target = (WORKSPACE_DIR / candidate).resolve()

    if target != WORKSPACE_DIR and WORKSPACE_DIR not in target.parents:
        raise ValueError(
            f"'{path}' resolves outside the Jarvis workspace ({WORKSPACE_DIR})."
        )

    return target


def read_file(path: str) -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)
    if not target.exists():
        return f"'{path}' does not exist in the workspace."
    if target.is_dir():
        return f"'{path}' is a directory, not a file."
    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > MAX_READ_CHARS:
        remaining = len(content) - MAX_READ_CHARS
        return content[:MAX_READ_CHARS] + f"\n[... truncated, {remaining} more characters ...]"
    return content


def write_file(path: str, content: str, append: bool = False) -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    action = "Appended to" if append else "Wrote"
    return f"{action} '{target.relative_to(WORKSPACE_DIR)}' ({len(content)} characters)."


def delete_file(path: str) -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)
    if not target.exists():
        return f"'{path}' does not exist."
    if target.is_dir():
        return f"'{path}' is a directory -- refusing to delete directories."
    target.unlink()
    return f"Deleted '{target.relative_to(WORKSPACE_DIR)}'."


def list_workspace(path: str = ".") -> str:
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)
    if not target.exists():
        return f"'{path}' does not exist."
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
    return "\n".join(entries) if entries else "(empty)"


FILE_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read the contents of a text file from the Jarvis workspace folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write text to a file in the Jarvis workspace folder.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a single file from the Jarvis workspace folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "list_workspace",
        "description": "List files and folders inside the Jarvis workspace folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
    }},
]

FILE_TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "delete_file": delete_file,
    "list_workspace": list_workspace,
}
