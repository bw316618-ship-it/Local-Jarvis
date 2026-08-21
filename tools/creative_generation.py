"""Story-grounded generation helpers for Creative Mode."""

from pathlib import Path

from memory import document_store, project_memory
from voice import document_state


def _registered_project_documents(project: str) -> set[str]:
    """Return the active project's authoritative document-path allowlist."""
    return {
        str(Path(path).expanduser().resolve())
        for path in project_memory.get_document_paths(project)
        if path
    }


def get_creative_context(query: str, k: int = 8, query_embedding: list = None) -> str:
    active = document_state.get_active_document()
    project = document_state.get_active_project()

    if not active and not project:
        # Preserve the existing public/test contract for the no-scope state.
        return (
            "No creative document is active. Ingest the story before "
            "generating story-specific material."
        )

    # A project is the authoritative scope. If runtime state contains an
    # active document that is not registered in that project, it is stale or
    # corrupted and MUST NOT be used for retrieval. Clear it, then fall back
    # to project-wide retrieval over the registered documents.
    if active and project:
        registered = _registered_project_documents(project)
        normalized_active = str(Path(active).expanduser().resolve())

        if normalized_active not in registered:
            document_state.clear_active_document()
            active = None

    kwargs = {
        "source_type": document_store.MANUAL,
        "k": k,
        "query_embedding": query_embedding,
    }

    # An active document is valid only when it belongs to the active project.
    # Otherwise the project itself defines the retrieval boundary.
    if active:
        kwargs["source"] = active
    else:
        kwargs["project"] = project

    result = document_store.search(query, **kwargs)
    documents = result["documents"]

    if not documents:
        scope = (
            f"project '{project}'"
            if project and not active
            else "the active document"
        )
        return f"No indexed passages from {scope} matched '{query}'."

    return "\n\n".join(
        f"[Story passage {i}]\n{doc.strip()}"
        for i, doc in enumerate(documents, 1)
    )


def build_chapter_ideas_context(
    request: str,
    k: int = 10,
    query_embedding: list = None,
) -> str:
    return get_creative_context(
        request,
        k=k,
        query_embedding=query_embedding,
    )


def build_scene_context(
    request: str,
    k: int = 10,
    query_embedding: list = None,
) -> str:
    return get_creative_context(
        request,
        k=k,
        query_embedding=query_embedding,
    )


CREATIVE_GENERATION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_creative_context",
            "description": "Retrieve story passages from the active creative scope.",
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
            "name": "build_chapter_ideas_context",
            "description": "Retrieve canon relevant to possible next chapters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "k": {"type": "integer"},
                },
                "required": ["request"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_scene_context",
            "description": "Retrieve canon relevant to a scene or chapter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "k": {"type": "integer"},
                },
                "required": ["request"],
            },
        },
    },
]

CREATIVE_GENERATION_TOOL_FUNCTIONS = {
    "get_creative_context": get_creative_context,
    "build_chapter_ideas_context": build_chapter_ideas_context,
    "build_scene_context": build_scene_context,
}

CREATIVE_GENERATION_RISKY_TOOLS = set()
