"""
File management tools for Jarvis.

All read/write/delete operations are sandboxed to a single `workspace/`
directory at the project root. This is deliberate: the model decides which
tool calls to make, so giving it unrestricted filesystem access would mean
one bad tool call (or a prompt-injected one, e.g. from ingested document
content) could read or destroy files anywhere on your machine. Confining it
to a workspace folder means the worst case is Jarvis makes a mess of its own
sandbox, not your system.

Move files in and out of workspace/ manually if you want Jarvis to work on
them. If you need broader access later, that's a deliberate choice to make
by widening _safe_path, not a default to fall into.
"""

from pathlib import Path

# Project root (Local-Jarvis/), then a dedicated sandbox folder inside it.
BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

MAX_READ_CHARS = 8000


def _safe_path(path: str) -> Path:
    """Resolve `path` relative to WORKSPACE_DIR and refuse to leave it."""
    candidate = Path(path)

    # Strip a leading root/drive so an absolute path can't escape the
    # sandbox by pointing somewhere else entirely.
    if candidate.is_absolute():
        candidate = Path(*candidate.parts[1:])

    target = (WORKSPACE_DIR / candidate).resolve()

    if target != WORKSPACE_DIR and WORKSPACE_DIR not in target.parents:
        raise ValueError(
            f"'{path}' resolves outside the Jarvis workspace ({WORKSPACE_DIR})."
        )

    return target


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def read_file(path: str) -> str:
    """Read a text file from the workspace."""
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
        return content[:MAX_READ_CHARS] + f"\n\n[... truncated, {remaining} more characters ...]"
    return content


def write_file(path: str, content: str, append: bool = False) -> str:
    """Write (or append to) a text file in the workspace, creating folders as needed."""
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)

    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(target, mode, encoding="utf-8") as f:
        f.write(content)

    action = "Appended to" if append else "Wrote"
    shown_path = target.relative_to(WORKSPACE_DIR)
    return f"{action} '{shown_path}' ({len(content)} characters)."


def delete_file(path: str) -> str:
    """Delete a single file in the workspace. Refuses to delete directories."""
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
    """List files and folders inside the Jarvis workspace."""
    try:
        target = _safe_path(path)
    except ValueError as e:
        return str(e)

    if not target.exists():
        return f"'{path}' does not exist."

    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
    return "\n".join(entries) if entries else "(empty)"


# ---------------------------------------------------------------------------
# Schemas (Ollama / OpenAI-style function-calling format)
# ---------------------------------------------------------------------------

FILE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file from the Jarvis workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the workspace folder.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write text to a file in the Jarvis workspace folder, creating it "
                "(and any parent folders) if it doesn't exist. Overwrites by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the workspace folder.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write to the file.",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "If true, append to the file instead of overwriting it. Defaults to false.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a single file (not a directory) from the Jarvis workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the workspace folder.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace",
            "description": "List files and folders inside the Jarvis workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Subfolder to list, relative to the workspace folder. Defaults to the workspace root.",
                    },
                },
                "required": [],
            },
        },
    },
]

FILE_TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "delete_file": delete_file,
    "list_workspace": list_workspace,
}
