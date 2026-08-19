"""
Shared document indexing for Jarvis's document stores.

Documents are tagged with source_type:
- "manual": deliberately ingested knowledge-base documents.
- "discovered": automatically indexed local files.

Search can additionally be scoped to an exact source path or named creative
project. Project metadata is optional and does not change the existing
path -> mtime incremental-index state contract.
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

    if source is not None:
        conditions.append(
            {"source": str(Path(source).expanduser().resolve())}
        )

    if project is not None:
        conditions.append({"project": project})

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
