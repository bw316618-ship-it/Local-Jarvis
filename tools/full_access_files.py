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


def rename_file(path: str, new_name: str) -> str:
    """Rename a file in place -- same directory, new filename."""
    try:
        target = Path(path).expanduser().resolve()
    except Exception as e:
        return f"Invalid path '{path}': {e}"

    if not target.exists():
        return f"'{path}' does not exist."
    if target.is_dir():
        return f"'{path}' is a directory -- refusing to rename directories."
    if not new_name or "/" in new_name or "\\" in new_name:
        return "new_name must be a plain filename, not a path."

    destination = target.parent / new_name
    if destination.exists():
        return f"'{destination}' already exists -- refusing to overwrite it."

    try:
        target.rename(destination)
        return f"Renamed '{target}' to '{destination}'."
    except Exception as e:
        return f"Could not rename '{path}': {e}"


def move_file(source: str, destination_dir: str, new_name: str = None) -> str:
    """Move a file into a directory, creating the directory if it doesn't
    exist yet. Optionally rename it in the same step."""
    try:
        src = Path(source).expanduser().resolve()
    except Exception as e:
        return f"Invalid source path '{source}': {e}"

    if not src.exists():
        return f"'{source}' does not exist."
    if src.is_dir():
        return f"'{source}' is a directory -- refusing to move directories."

    try:
        dest_dir = Path(destination_dir).expanduser().resolve()
    except Exception as e:
        return f"Invalid destination '{destination_dir}': {e}"

    if dest_dir.exists() and dest_dir.is_file():
        return f"'{destination_dir}' is an existing file, not a directory."

    filename = new_name if new_name else src.name
    if not filename or "/" in filename or "\\" in filename:
        return "new_name must be a plain filename, not a path."

    dst = dest_dir / filename
    if dst.exists():
        return f"'{dst}' already exists -- refusing to overwrite it."

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"Moved '{src}' to '{dst}'."
    except Exception as e:
        return f"Could not move '{source}' to '{dst}': {e}"


# Extension -> subfolder name, used by organize_directory. Anything not
# listed here lands in an "other" subfolder rather than being skipped.
ORGANIZE_CATEGORIES = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".heic"},
    "documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
    "spreadsheets": {".xls", ".xlsx", ".csv", ".ods"},
    "presentations": {".ppt", ".pptx", ".odp"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".cpp", ".c", ".sh", ".bat", ".ps1"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
}


def _category_for(suffix: str) -> str:
    suffix = suffix.lower()
    for category, extensions in ORGANIZE_CATEGORIES.items():
        if suffix in extensions:
            return category
    return "other"


def organize_directory(path: str) -> str:
    """Sort files directly inside a directory into subfolders by type
    (images/, documents/, code/, etc.), creating those subfolders as
    needed. Only touches top-level files -- doesn't recurse into existing
    subfolders, so it won't re-shuffle something already organized."""
    try:
        target = Path(path).expanduser().resolve()
    except Exception as e:
        return f"Invalid path '{path}': {e}"

    if not target.exists():
        return f"'{path}' does not exist."
    if not target.is_dir():
        return f"'{path}' is not a directory."

    # Snapshot the file list first -- we're about to create subfolders
    # inside this same directory and don't want to iterate into them.
    files = [p for p in target.iterdir() if p.is_file()]

    moved = 0
    skipped = 0
    errors = []

    for file_path in files:
        dest_dir = target / _category_for(file_path.suffix)
        dest_path = dest_dir / file_path.name

        if dest_path.exists():
            skipped += 1
            continue

        try:
            dest_dir.mkdir(exist_ok=True)
            file_path.rename(dest_path)
            moved += 1
        except Exception as e:
            errors.append(f"{file_path.name}: {e}")

    summary = f"Organized '{path}': {moved} file(s) moved, {skipped} skipped (already existed at destination)."
    if errors:
        summary += f" {len(errors)} error(s): " + "; ".join(errors[:5])
    return summary


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
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": "Rename a file in place, keeping it in the same folder but giving it a new filename.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full or relative path to the file to rename."},
                    "new_name": {"type": "string", "description": "The new filename (not a path) -- e.g. 'report_final.pdf'."},
                },
                "required": ["path", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move a file into a directory (created automatically if it doesn't exist), optionally renaming it in the same step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Full or relative path to the file to move."},
                    "destination_dir": {"type": "string", "description": "The folder to move it into. Created automatically if it doesn't already exist."},
                    "new_name": {"type": "string", "description": "Optional new filename to give it during the move. Defaults to keeping its current name."},
                },
                "required": ["source", "destination_dir"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "organize_directory",
            "description": (
                "Sort files directly inside a folder into subfolders by type "
                "(images/, documents/, spreadsheets/, code/, etc.), creating "
                "those subfolders as needed. Use this for requests like "
                "'organize my Downloads'. Only affects top-level files, not "
                "files already inside subfolders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full or relative path to the folder to organize."},
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
    "rename_file": rename_file,
    "move_file": move_file,
    "organize_directory": organize_directory,
}

FULL_ACCESS_RISKY_TOOLS = {"write_any_file", "delete_any_file", "rename_file", "move_file", "organize_directory"}
