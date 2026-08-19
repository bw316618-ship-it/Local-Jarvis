"""Persistent registry of named creative projects."""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_PATH = BASE_DIR / "memory" / "creative_projects.json"


def _load():
    if not PROJECTS_PATH.exists():
        return {}
    try:
        value = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(projects):
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_PATH.write_text(
        json.dumps(projects, indent=2),
        encoding="utf-8",
    )


def _key(name):
    return " ".join((name or "").strip().lower().split())


def ensure_project(name):
    display = " ".join((name or "").strip().split())
    key = _key(display)

    if not key:
        raise ValueError("Creative project name cannot be empty.")

    projects = _load()

    if key not in projects:
        projects[key] = {
            "name": display,
            "documents": [],
        }
        _save(projects)

    return projects[key]


def get_project(name):
    return _load().get(_key(name))


def list_projects():
    return _load()


def add_document(project, path):
    display = " ".join((project or "").strip().split())
    key = _key(display)

    if not key:
        raise ValueError("Creative project name cannot be empty.")

    projects = _load()
    resolved = str(Path(path).expanduser().resolve())

    if key not in projects:
        projects[key] = {"name": display, "documents": []}

    documents = projects[key].setdefault("documents", [])
    if resolved not in documents:
        documents.append(resolved)

    _save(projects)
    return projects[key]


def get_document_paths(project):
    record = get_project(project)
    if not record:
        return []
    return list(record.get("documents", []))


def describe_project(project):
    record = get_project(project)

    if not record:
        return f"Creative project '{project}' does not exist."

    docs = record.get("documents", [])
    lines = [
        f"Active creative project: '{record.get('name', project)}'.",
        f"Documents: {len(docs)}",
    ]
    lines.extend(f"- {path}" for path in docs)
    return "\n".join(lines)
