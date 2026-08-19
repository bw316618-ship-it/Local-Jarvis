"""
Active document scope for document-aware modes such as creative mode.

The state stores only the resolved document path. Retrieval remains in
memory/document_store.py, where source_type and source filtering are enforced.
"""

from pathlib import Path
import threading

_lock = threading.Lock()
_active_document = None


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
