"""
Active creative document/project scope.
"""

from pathlib import Path
import threading

_lock = threading.Lock()
_active_document = None
_active_project = None


def set_active_document(path: str) -> str:
    resolved = str(Path(path).expanduser().resolve())

    with _lock:
        global _active_document
        _active_document = resolved

    return resolved


def clear_active_document() -> None:
    global _active_document

    with _lock:
        _active_document = None


def get_active_document():
    with _lock:
        return _active_document


def set_active_project(name: str) -> str:
    name = " ".join((name or "").strip().split())
    if not name:
        raise ValueError("Creative project name cannot be empty.")

    global _active_project
    global _active_document
    with _lock:
        _active_project = name
        _active_document = None

    return name


def clear_active_project() -> None:
    global _active_project

    with _lock:
        _active_project = None


def get_active_project():
    with _lock:
        return _active_project


def clear_scope() -> None:
    global _active_document, _active_project

    with _lock:
        _active_document = None
        _active_project = None
