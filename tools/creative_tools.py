"""
Tools for creative/document-scoped mode.

Creative mode only retrieves from the currently active document. It does
not expose general whole-computer file search.
"""

from pathlib import Path

from config import CONFIG
from memory import document_store
from memory.shared import get_embedder
from voice import document_state


def set_creative_document(path: str) -> str:
    target = Path(path).expanduser().resolve()

    if not target.exists():
        return f"Document '{path}' does not exist."

    if not target.is_file():
        return f"'{path}' is not a file."

    active = document_state.set_active_document(str(target))

    return f"Creative document set to '{active}'."


def clear_creative_document() -> str:
    document_state.clear_active_document()
    return "Creative document cleared."


def search_creative_document(query: str, k: int = 6) -> str:
    active = document_state.get_active_document()

    if not active:
        return (
            "No creative document is active. Set the story/PDF with "
            "set_creative_document first."
        )

    result = document_store.search(
        query,
        source_type=document_store.MANUAL,
        k=k,
        source=active,
    )

    # If the story was discovered by the whole-computer indexer rather than
    # manually ingested, allow the same document-scoped retrieval.
    if not result["documents"]:
        result = document_store.search(
            query,
            source_type=document_store.DISCOVERED,
            k=k,
            source=active,
        )

    documents = result["documents"]
    metadatas = result["metadatas"]

    if not documents:
        return (
            f"No indexed passages from the active document matched '{query}'. "
            "Index or ingest the document first."
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
                "All document-scoped creative retrieval will use this file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Local path to the story, PDF, or writing document.",
                    }
                },
                "required": ["path"],
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
                "Search the active creative document for relevant passages. "
                "Use this before making story-specific claims or generating "
                "chapter ideas grounded in the document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Story detail, character, plot point, theme, or passage to retrieve.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of relevant passages to return.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

CREATIVE_TOOL_FUNCTIONS = {
    "set_creative_document": set_creative_document,
    "clear_creative_document": clear_creative_document,
    "search_creative_document": search_creative_document,
}

CREATIVE_RISKY_TOOLS = set()
