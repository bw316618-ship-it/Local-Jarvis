"""
Local task/calendar tool for Jarvis.

Tasks are stored as VTODO components in a single local .ics file
(memory/jarvis_calendar.ics) using the icalendar package -- a real,
standard calendar format, so the file can be opened, synced, or imported
into any calendar app that reads ICS, not just a Jarvis-only format.

This deliberately models "tasks with a due date" (add/list/complete/
delete) rather than full calendar events with start/end times and
attendees -- that covers the "remind me to X on Y" use case this tool
exists for, without building a full event-scheduling system.

Date strings accept ISO ('2026-08-20') and most common human formats,
via python-dateutil -- but NOT relative terms like 'tomorrow' or 'next
Monday'. The model should resolve those against get_current_time first
and pass an absolute date in.

add_task/list_tasks/complete_task are safe: they persist to disk but are
easily reversible (complete a task by mistake, complete the right one
after). delete_task is risky since it's a permanent, harder-to-undo
removal, consistent with how this codebase treats other destructive
operations (see tools/file_manager.py's delete_file).
"""

import uuid
from datetime import datetime
from pathlib import Path

from dateutil import parser as date_parser
from icalendar import Calendar, Todo

BASE_DIR = Path(__file__).resolve().parent.parent
CALENDAR_PATH = BASE_DIR / "memory" / "jarvis_calendar.ics"


def _load_calendar() -> Calendar:
    if CALENDAR_PATH.exists():
        try:
            return Calendar.from_ical(CALENDAR_PATH.read_bytes())
        except Exception:
            pass  # corrupted file -- start fresh rather than crash every call
    cal = Calendar()
    cal.add("prodid", "-//Local-Jarvis//jarvis_calendar//EN")
    cal.add("version", "2.0")
    return cal


def _save_calendar(cal: Calendar) -> None:
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_PATH.write_bytes(cal.to_ical())


def _parse_date(date_str: str):
    """Parse a date string into a date object. Raises ValueError/OverflowError
    on anything unparseable -- callers should catch and report those."""
    return date_parser.parse(date_str).date()


def _set_status(todo: Todo, status: str) -> None:
    if "status" in todo:
        del todo["status"]
    todo.add("status", status)


def add_task(title: str, due_date: str, notes: str = "") -> str:
    """Add a task due on a given date."""
    title = (title or "").strip()
    if not title:
        return "A task title is required."

    try:
        due = _parse_date(due_date)
    except (ValueError, OverflowError):
        return f"Could not understand the date '{due_date}'. Try a format like '2026-08-20'."

    cal = _load_calendar()
    todo = Todo()
    todo.add("uid", str(uuid.uuid4()))
    todo.add("summary", title)
    todo.add("due", due)
    todo.add("dtstamp", datetime.now())
    _set_status(todo, "NEEDS-ACTION")
    if notes.strip():
        todo.add("description", notes.strip())
    cal.add_component(todo)
    _save_calendar(cal)

    return f"Added task '{title}' due {due.isoformat()}."


def list_tasks(due_date: str = "") -> str:
    """List tasks. If `due_date` is given, only tasks due that day;
    otherwise every pending (not-yet-completed) task."""
    cal = _load_calendar()

    filter_date = None
    if due_date.strip():
        try:
            filter_date = _parse_date(due_date)
        except (ValueError, OverflowError):
            return f"Could not understand the date '{due_date}'. Try a format like '2026-08-20'."

    lines = []
    for component in cal.walk("VTODO"):
        status = str(component.get("status", "NEEDS-ACTION"))
        due_prop = component.get("due")
        due_val = due_prop.dt if due_prop else None

        if filter_date is not None and due_val != filter_date:
            continue
        if filter_date is None and status == "COMPLETED":
            continue  # default view is "what's still pending"

        title = str(component.get("summary", "(untitled)"))
        due_str = due_val.isoformat() if due_val else "no due date"
        marker = "[done]" if status == "COMPLETED" else "[ ]"
        lines.append(f"{marker} {title} -- due {due_str}")

    if not lines:
        return "No tasks due that day." if filter_date else "No pending tasks."
    return "\n".join(lines)


def _find_unique_match(cal: Calendar, title_query: str):
    """Return (matches list). Caller decides how to react to 0/many matches."""
    return [c for c in cal.walk("VTODO") if title_query in str(c.get("summary", "")).lower()]


def complete_task(title: str) -> str:
    """Mark a task as completed, matched by a case-insensitive substring of its title."""
    title_query = (title or "").strip().lower()
    if not title_query:
        return "A task title is required."

    cal = _load_calendar()
    matches = _find_unique_match(cal, title_query)

    if not matches:
        return f"No task found matching '{title}'."
    if len(matches) > 1:
        names = "; ".join(str(m.get("summary", "")) for m in matches)
        return f"Multiple tasks match '{title}': {names}. Be more specific."

    _set_status(matches[0], "COMPLETED")
    _save_calendar(cal)
    return f"Marked '{matches[0].get('summary')}' as completed."


def delete_task(title: str) -> str:
    """Permanently remove a task, matched by a case-insensitive substring of its title."""
    title_query = (title or "").strip().lower()
    if not title_query:
        return "A task title is required."

    cal = _load_calendar()
    matches = _find_unique_match(cal, title_query)

    if not matches:
        return f"No task found matching '{title}'."
    if len(matches) > 1:
        names = "; ".join(str(m.get("summary", "")) for m in matches)
        return f"Multiple tasks match '{title}': {names}. Be more specific."

    cal.subcomponents.remove(matches[0])
    _save_calendar(cal)
    return f"Deleted task '{matches[0].get('summary')}'."


CALENDAR_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a task/reminder due on a specific date to Jarvis's local calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short description of the task."},
                    "due_date": {
                        "type": "string",
                        "description": "Due date, e.g. '2026-08-20'. Resolve relative terms like 'tomorrow' against the current date first.",
                    },
                    "notes": {"type": "string", "description": "Optional additional detail about the task."},
                },
                "required": ["title", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks from Jarvis's local calendar -- pending tasks by default, or tasks due on a specific date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "due_date": {
                        "type": "string",
                        "description": "Optional date to filter by, e.g. '2026-08-20'. Omit to list all pending tasks.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed, matched by (part of) its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The task's title, or a distinguishing part of it."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Permanently delete a task, matched by (part of) its title. Use complete_task instead if the task is just done, not wrong.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The task's title, or a distinguishing part of it."},
                },
                "required": ["title"],
            },
        },
    },
]

CALENDAR_TOOL_FUNCTIONS = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "delete_task": delete_task,
}

# Deleting a task is a permanent, harder-to-undo removal -- gets the same
# confirmation gate as other destructive operations. Adding/listing/
# completing are safe: they persist data but nothing is lost.
CALENDAR_RISKY_TOOLS = {"delete_task"}
