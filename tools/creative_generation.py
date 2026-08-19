"""Story-grounded generation helpers for Creative Mode."""

from memory import document_store
from voice import document_state


def get_creative_context(query: str, k: int = 8) -> str:
    active = document_state.get_active_document()
    project = document_state.get_active_project()

    if not active and not project:
        return (
            "No creative document is active. Ingest the story before "
            "generating story-specific material."
        )

    kwargs = {
        "source_type": document_store.MANUAL,
        "k": k,
    }

    # A selected document wins. Otherwise a project is the retrieval boundary.
    if active:
        kwargs["source"] = active
    else:
        kwargs["project"] = project

    result = document_store.search(query, **kwargs)
    documents = result["documents"]

    if not documents:
        scope = f"project '{project}'" if project and not active else "the active document"
        return f"No indexed passages from {scope} matched '{query}'."

    return "\n\n".join(
        f"[Story passage {i}]\n{doc.strip()}"
        for i, doc in enumerate(documents, 1)
    )


def build_chapter_ideas_context(request: str, k: int = 10) -> str:
    return get_creative_context(request, k=k)


def build_scene_context(request: str, k: int = 10) -> str:
    return get_creative_context(request, k=k)


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
