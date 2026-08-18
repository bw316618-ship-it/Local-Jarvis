"""
Shared document indexing for Jarvis's two RAG stores: ingest/ingest.py's
manually-curated docs and tools/file_index.py's whole-computer semantic
search. Both write into one "jarvis_documents" collection, tagged by a
`source_type` metadata field ("manual" or "discovered"), with one shared
state file instead of two near-identical ones.

Callers still get separate-feeling behavior (memory/retriever.py only
ever searches "manual" docs; tools/file_index.py's search_files only
searches "discovered" files) via the `source_type` filter on search --
the merge removes duplicate code, not the conceptual distinction between
"things I fed Jarvis on purpose" and "things Jarvis found on disk".
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


def index_one_file(path: Path, text: str, source_type: str, chunk_size: int, chunk_overlap: int, state: dict) -> int:
    """Chunk + embed one file's text, replacing any previously-indexed
    chunks for it. Returns the number of chunks written. Caller is
    responsible for the mtime check and for calling save_state(state)
    once it's done batching files."""
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
            {"source": key, "filename": path.name, "source_type": source_type}
            for _ in chunks
        ]
        collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)

    state[key] = path.stat().st_mtime
    return len(chunks)


def search(query: str, source_type: str, k: int = 5, query_embedding: list = None) -> dict:
    """`query_embedding`, if given, is used instead of re-encoding `query`
    -- callers that already need the same query's embedding elsewhere in
    the same turn (brain/llm.py encodes it once and reuses it across all
    three memory lookups) can pass it through instead of paying for a
    second/third embedding inference on an identical string."""
    collection = get_collection()
    if collection.count() == 0:
        return {"documents": [], "metadatas": []}

    embedding = query_embedding if query_embedding is not None else get_embedder().encode(query).tolist()
    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(k * 3, collection.count()),  # over-fetch, then filter by source_type
        where={"source_type": source_type},
    )
    documents = (results.get("documents") or [[]])[0][:k]
    metadatas = (results.get("metadatas") or [[]])[0][:k]
    return {"documents": documents, "metadatas": metadatas}
