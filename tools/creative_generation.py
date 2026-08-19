"""Story-grounded generation helpers for Creative Mode."""

from memory import document_store
from voice import document_state


def _get_active_document_or_error():
    active = document_state.get_active_document()
    if not active:
        return None, (
            "No creative document is active. Ingest the story before "
            "generating story-specific material."
        )
    return active, None


def get_creative_context(query: str, k: int = 8) -> str:
    active, error = _get_active_document_or_error()
    if error:
        return error

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


def build_chapter_ideas_context(
    request: str,
    k: int = 10,
) -> str:
    """Retrieve canon relevant to proposing possible next chapters."""
    return get_creative_context(
        (
            "chapter development; current plot; characters; relationships; "
            "conflicts; unresolved threads; recent events; consequences; "
            f"user request: {request}"
        ),
        k=k,
    )


def build_scene_context(
    request: str,
    k: int = 10,
) -> str:
    """Retrieve canon relevant to writing a scene or chapter."""
    return get_creative_context(
        (
            "scene and chapter continuity; characters; setting; dialogue; "
            "events; motivations; established facts; unresolved threads; "
            f"writing request: {request}"
        ),
        k=k,
    )


CREATIVE_GENERATION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_creative_context",
            "description": (
                "Retrieve story passages from the active creative document "
                "to ground a creative-writing response in established canon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What story material is needed.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of passages.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_chapter_ideas_context",
            "description": (
                "Retrieve canon relevant to generating several possible "
                "directions for a next chapter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "The chapter-development request.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of passages.",
                    },
                },
                "required": ["request"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_scene_context",
            "description": (
                "Retrieve canon relevant to writing a new scene or chapter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "The scene or chapter-writing request.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of passages.",
                    },
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
