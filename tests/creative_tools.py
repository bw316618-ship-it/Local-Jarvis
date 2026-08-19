"""
Creative/document-scoped tools.

Creative Mode has its own document boundary. The active document is stored
separately from general Jarvis memory, and retrieval is restricted by both
source_type and exact source path.
"""

from pathlib import Path

from config import CONFIG
from memory import document_store
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


def ingest_creative_document(path: str) -> str:
    """Extract and index one story/document as a manually curated document."""
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
        text = _read_document(target)
    except Exception as e:
        return f"Could not read '{path}': {e}"

    if not text.strip():
        return f"Document '{path}' contains no extractable text."

    state = document_store.load_state()

    try:
        chunk_count = document_store.index_one_file(
            target,
            text,
            document_store.MANUAL,
            CONFIG["index_chunk_size"],
            CONFIG["index_chunk_overlap"],
            state,
        )
        document_store.save_state(state)
    except Exception as e:
        return f"Could not index '{path}': {e}"

    document_state.set_active_document(str(target))

    return (
        f"Creative document ingested: '{target}'. "
        f"Indexed {chunk_count} passages and made it the active document."
    )


def get_creative_document() -> str:
    active = document_state.get_active_document()

    if not active:
        return "No creative document is active."

    target = Path(active)

    if not target.exists():
        return f"Creative document '{active}' is no longer available on disk."

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
    metadatas = result["metadatas"]

    if not documents:
        return (
            f"No indexed passages from the active document matched '{query}'. "
            "Ingest the document first."
        )

    lines = [f"Relevant passages from '{active}':"]

    for index, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        lines.append(f"\n[{index}]")
        lines.append(doc.strip())

    return "\n".join(lines)


CREATIVE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_creative_document",
            "description": (
                "Set the active story/PDF/document for creative writing work. "
                "This does not index the document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Local path to the story, PDF, Markdown, or text document.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_creative_document",
            "description": (
                "Extract and index a story/PDF/Markdown/text document into "
                "the creative document store, then make it active."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Local path to the story or document.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_creative_document",
            "description": "Return the currently active creative document.",
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
            "description": "Clear the currently active creative document.",
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
            "description": (
                "Search only the active creative document for relevant story "
                "passages. Use this before making story-specific claims, "
                "chapter ideas, or scene suggestions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Character, event, relationship, location, theme, or plot point.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of passages to return.",
                    },
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
