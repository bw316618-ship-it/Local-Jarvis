"""
Unrestricted file tools for Jarvis -- read, write, and delete anywhere on
the machine, not just the sandboxed workspace/ folder used by
tools/file_manager.py.

Reads are auto-approved (read-only, non-destructive, and you explicitly
asked for Jarvis to have full access). Writes and deletes are registered
as risky in tools/tools.py, so Jarvis confirms with you before touching
anything outside its own sandbox.
"""

from pathlib import Path

MAX_READ_CHARS = 8000


def read_any_file(path: str) -> str:
    """Read a text file from anywhere on the machine."""
    try:
        target = Path(path).expanduser().resolve()
    except Exception as e:
        return f"Invalid path '{path}': {e}"

    if not target.exists():
        return f"'{path}' does not exist."
    if target.is_dir():
        return f"'{path}' is a directory, not a file."

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Could not read '{path}': {e}"

    if len(content) > MAX_READ_CHARS:
        remaining = len(content) - MAX_READ_CHARS
        return content[:MAX_READ_CHARS] + f"\n\n[... truncated, {remaining} more characters ...]"
    return content


def write_any_file(path: str, content: str, append: bool = False) -> str:
    """Write (or append) to a file anywhere on the machine, creating folders as needed."""
    try:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if append else "Wrote"
        return f"{action} '{target}' ({len(content)} characters)."
    except Exception as e:
        return f"Could not write '{path}': {e}"


def delete_any_file(path: str) -> str:
    """Delete a single file anywhere on the machine. Refuses directories."""
    try:
        target = Path(path).expanduser().resolve()
    except Exception as e:
        return f"Invalid path '{path}': {e}"

    if not target.exists():
        return f"'{path}' does not exist."
    if target.is_dir():
        return f"'{path}' is a directory -- refusing to delete directories."

    try:
        target.unlink()
        return f"Deleted '{target}'."
    except Exception as e:
        return f"Could not delete '{path}': {e}"


FULL_ACCESS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_any_file",
            "description": "Read a text file from anywhere on the local machine (not limited to the workspace folder).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full or relative path to the file."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_any_file",
            "description": "Write or append text to a file anywhere on the local machine, creating parent folders as needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full or relative path to the file."},
                    "content": {"type": "string", "description": "Text content to write."},
                    "append": {"type": "boolean", "description": "Append instead of overwrite. Defaults to false."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_any_file",
            "description": "Delete a single file anywhere on the local machine (not a directory).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full or relative path to the file."},
                },
                "required": ["path"],
            },
        },
    },
]

FULL_ACCESS_FUNCTIONS = {
    "read_any_file": read_any_file,
    "write_any_file": write_any_file,
    "delete_any_file": delete_any_file,
}

FULL_ACCESS_RISKY_TOOLS = {"write_any_file", "delete_any_file"}
