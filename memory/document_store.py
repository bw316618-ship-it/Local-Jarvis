"""
Shared document indexing for Jarvis's document stores.

Documents are tagged with source_type:
- "manual": deliberately ingested knowledge-base documents.
- "discovered": automatically indexed local files.

Creative projects are hard retrieval boundaries. When `project` is supplied,
the project's registered document paths are used as the authoritative source
allowlist. Chroma's stored `project` metadata is deliberately NOT trusted as
the project boundary because old indexed chunks can contain stale metadata.
"""

import json
from pathlib import Path

from memory.shared import get_embedder, get_client

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "memory" / "document_index_state.json"
COLLECTION_NAME = "jarvis_documents"

MANUAL = "manual"
DISCOVERED = "discovered"


def get_collection():
    return get_client().get_or_create_collection(COLLECTION_NAME)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def chunk_text(text: str, chunk_size: int, chunk_overlap: int):
    words = text.split()
    if not words:
        return

    step = max(chunk_size - chunk_overlap, 1)

    for i in range(0, len(words), step):
        yield " ".join(words[i:i + chunk_size])


def index_one_file(
    path: Path,
    text: str,
    source_type: str,
    chunk_size: int,
    chunk_overlap: int,
    state: dict,
    project: str = None,
) -> int:
    """Replace all indexed chunks for one file."""
    if source_type not in {MANUAL, DISCOVERED}:
        raise ValueError(f"Unknown document source_type: {source_type}")

    collection = get_collection()
    embedder = get_embedder()
    key = str(path.resolve())

    try:
        collection.delete(where={"source": key})
    except Exception:
        pass

    chunks = list(chunk_text(text, chunk_size, chunk_overlap))

    if chunks:
        embeddings = embedder.encode(chunks).tolist()
        ids = [f"{key}::{idx}" for idx in range(len(chunks))]
        metadatas = [
            {
                "source": key,
                "filename": path.name,
                "source_type": source_type,
                "project": project or "",
            }
            for _ in chunks
        ]

        collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )

    # IMPORTANT: keep this as a float. file_index.py depends on this exact
    # state shape for incremental indexing.
    state[key] = path.stat().st_mtime
    return len(chunks)


def search(
    query: str,
    source_type: str,
    k: int = 5,
    query_embedding: list = None,
    source: str = None,
    project: str = None,
) -> dict:
    """Search indexed documents with explicit creative/project scoping.

    `source` means one exact document.

    `project` means the active project's REGISTERED document paths. The
    registry is authoritative. Stored vector metadata is not sufficient to
    establish project membership because an old indexed document can retain
    stale `project` metadata after it is removed from the project.

    Keeping `project` in the function signature is intentional: existing
    callers and tests use it as the public project-scope argument.
    """
    if source_type not in {MANUAL, DISCOVERED}:
        raise ValueError(f"Unknown document source_type: {source_type}")

    collection = get_collection()

    if collection.count() == 0:
        return {"documents": [], "metadatas": []}

    embedding = (
        query_embedding
        if query_embedding is not None
        else get_embedder().encode(query).tolist()
    )

    conditions = [{"source_type": source_type}]

    if project is not None:
        # Import lazily to avoid coupling module initialization to the
        # persistent project registry.
        from memory import project_memory

        registered = project_memory.get_document_paths(project)
        registered = [
            str(Path(path).expanduser().resolve())
            for path in registered
            if path
        ]

        # An active project with no registered documents must search nothing.
        if not registered:
            return {"documents": [], "metadatas": []}

        # This is the critical security/grounding boundary. Do not also add
        # `{"project": project}` here: the registry, not stale vector
        # metadata, defines current project membership.
        conditions.append({"source": {"$in": registered}})

    if source is not None:
        normalized_source = str(
            Path(source).expanduser().resolve()
        )

        # If both project and source are supplied, the exact document must
        # also belong to the active project's registry.
        if project is not None:
            from memory import project_memory

            registered = {
                str(Path(path).expanduser().resolve())
                for path in project_memory.get_document_paths(project)
            }
            if normalized_source not in registered:
                return {"documents": [], "metadatas": []}

        conditions.append({"source": normalized_source})

    if len(conditions) == 1:
        where = conditions[0]
    else:
        where = {"$and": conditions}

    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(k * 3, collection.count()),
        where=where,
    )

    documents = (results.get("documents") or [[]])[0][:k]
    metadatas = (results.get("metadatas") or [[]])[0][:k]

    return {
        "documents": documents,
        "metadatas": metadatas,
    }
