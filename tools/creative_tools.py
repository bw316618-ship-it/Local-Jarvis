"""
Creative/document-scoped tools.

The original five document operations remain the public CREATIVE_TOOL_SCHEMAS
contract. Project operations live in PROJECT_TOOL_SCHEMAS so existing callers
that expect exactly the five document operations continue to work.
"""

from pathlib import Path

from config import CONFIG
from memory import document_store, project_memory
from voice import document_state

SUPPORTED_DOCUMENTS = {".txt", ".md", ".pdf"}


def _read_document(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    return path.read_text(encoding="utf-8", errors="ignore")


def set_creative_document(path: str) -> str:
    target = Path(path).expanduser().resolve()

    if not target.exists():
        return f"Document '{path}' does not exist."
    if not target.is_file():
        return f"'{path}' is not a file."
    if target.suffix.lower() not in SUPPORTED_DOCUMENTS:
        return (
            f"Unsupported creative document type '{target.suffix}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_DOCUMENTS))}."
        )

    active = document_state.set_active_document(str(target))
    return f"Creative document set to '{active}'."


def ingest_creative_document(path: str, category: str = "general") -> str:
    target = Path(path).expanduser().resolve()

    if not target.exists():
        return f"Document '{path}' does not exist."
    if not target.is_file():
        return f"'{path}' is not a file."
    if target.suffix.lower() not in SUPPORTED_DOCUMENTS:
        return (
            f"Unsupported creative document type '{target.suffix}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_DOCUMENTS))}."
        )

    try:
        state = document_store.load_state()
        current_mtime = target.stat().st_mtime
    except OSError as e:
        return f"Could not inspect '{path}': {e}"

    key = str(target)
    project = document_state.get_active_project()

    if state.get(key) == current_mtime:
        document_state.set_active_document(key)
        if project:
            project_memory.add_document(project, key)
        return (
            f"Creative document already indexed: '{target}'. "
            "Made it the active document."
        )

    try:
        text = _read_document(target)
    except Exception as e:
        return f"Could not read '{path}': {e}"

    if not text.strip():
        return f"Document '{path}' contains no extractable text."

    try:
        chunk_count = document_store.index_one_file(
            target,
            text,
            document_store.MANUAL,
            CONFIG["index_chunk_size"],
            CONFIG["index_chunk_overlap"],
            state,
            project=project,
        )
        document_store.save_state(state)
    except Exception as e:
        return f"Could not index '{path}': {e}"

    if project:
        project_memory.add_document(project, key)

    document_state.set_active_document(key)

    return (
        f"Creative document ingested: '{target}'. "
        f"Indexed {chunk_count} passages and made it the active document."
    )


def get_creative_document() -> str:
    active = document_state.get_active_document()

    if not active:
        return "No creative document is active."

    return f"Active creative document: '{active}'."


def clear_creative_document() -> str:
    document_state.clear_active_document()
    return "Creative document cleared."


def search_creative_document(query: str, k: int = 6) -> str:
    active = document_state.get_active_document()

    if not active:
        return (
            "No creative document is active. Set or ingest the story/PDF "
            "with set_creative_document or ingest_creative_document first."
        )

    result = document_store.search(
        query,
        source_type=document_store.MANUAL,
        k=k,
        source=active,
    )

    documents = result["documents"]

    if not documents:
        return (
            f"No indexed passages from the active document matched '{query}'."
        )

    return "\n\n".join(
        f"[Story passage {i}]\n{doc.strip()}"
        for i, doc in enumerate(documents, 1)
    )


# Existing contract: EXACTLY these five.
CREATIVE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_creative_document",
            "description": "Set the active story/PDF/document for creative work.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_creative_document",
            "description": "Extract and index a creative document.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_creative_document",
            "description": "Return the active creative document.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_creative_document",
            "description": "Clear the active creative document.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_creative_document",
            "description": "Search only the active creative document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]

CREATIVE_TOOL_FUNCTIONS = {
    "set_creative_document": set_creative_document,
    "ingest_creative_document": ingest_creative_document,
    "get_creative_document": get_creative_document,
    "clear_creative_document": clear_creative_document,
    "search_creative_document": search_creative_document,
}

CREATIVE_RISKY_TOOLS = set()


# Separate project contract.
def set_creative_project(name: str) -> str:
    try:
        record = project_memory.ensure_project(name)
    except ValueError as e:
        return str(e)

    document_state.set_active_project(record["name"])
    document_state.clear_active_document()

    return (
        f"Creative project active: '{record['name']}'. "
        f"{len(record.get('documents', []))} document(s) registered."
    )


def get_creative_project() -> str:
    project = document_state.get_active_project()
    if not project:
        return "No creative project is active."
    return project_memory.describe_project(project)


def list_creative_projects() -> str:
    projects = project_memory.list_projects()

    if not projects:
        return "No creative projects exist yet."

    return "\n".join(
        [
            "Creative projects:",
            *[
                f"- {record.get('name', key)} "
                f"({len(record.get('documents', []))} document(s))"
                for key, record in projects.items()
            ],
        ]
    )


def clear_creative_project() -> str:
    document_state.clear_scope()
    return "Creative project and document scope cleared."


def search_creative_project(query: str, k: int = 8) -> str:
    project = document_state.get_active_project()

    if not project:
        return "No creative project is active."

    result = document_store.search(
        query,
        source_type=document_store.MANUAL,
        k=k,
        project=project,
    )

    if not result["documents"]:
        return f"No indexed project passages matched '{query}'."

    return "\n\n".join(
        f"[Project passage {i}]\n{doc.strip()}"
        for i, doc in enumerate(result["documents"], 1)
    )


PROJECT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_creative_project",
            "description": "Activate a named creative project.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_creative_project",
            "description": "Show the active creative project.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_creative_projects",
            "description": "List saved creative projects.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_creative_project",
            "description": "Search all indexed documents in the active project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_creative_project",
            "description": "Clear the active project and document scope.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

PROJECT_TOOL_FUNCTIONS = {
    "set_creative_project": set_creative_project,
    "get_creative_project": get_creative_project,
    "list_creative_projects": list_creative_projects,
    "search_creative_project": search_creative_project,
    "clear_creative_project": clear_creative_project,
}

PROJECT_RISKY_TOOLS = set()
