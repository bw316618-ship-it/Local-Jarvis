"""
Long-term memory for Jarvis: two complementary stores.

`remember_turn`/`recall` -- generic conversation memory. Unlike
memory/retriever.py (documents you've manually ingested) and
tools/file_index.py (files found on disk), this stores a compact record
of past conversation turns -- so Jarvis can recall an earlier decision,
where you left off on a project, or something you told it weeks ago,
across separate runs of the app.

`remember_fact`/`recall_facts`/`list_facts` -- structured facts, kept in
a separate collection. Not everything worth remembering is "a turn" --
"my manager's name is Sarah" or "I prefer dark mode" are durable facts
that deserve their own category, and a way to list them directly rather
than only finding them via semantic search.

Both use the same retrieval pattern as the other memory stores: semantic
search (the top few relevant entries for whatever you're asking now), not
a full dump -- the local model's context window is too small for that,
and most stored history wouldn't be relevant to the current question.
Results are additionally filtered by a cosine-similarity floor (see
_filter_by_relevance below) -- a nearest-neighbor query always returns
its k closest matches even when the closest thing available still isn't
actually relevant, and that noise otherwise gets stuffed into the prompt
as if it were signal.

The embedder and ChromaDB client are shared singletons from
memory/shared.py -- see that module's docstring for why. forget_all() is
the one exception: it opens its own PersistentClient directly rather than
going through the shared one, since it's a rare, destructive operation
(deleting whole collections) and there's no benefit to sharing a
long-lived client for that.
"""

from datetime import datetime, timezone
from pathlib import Path
import math

import chromadb

from memory.shared import get_embedder, get_client
from voice import document_state

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"
COLLECTION_NAME = "jarvis_conversations"
FACTS_COLLECTION_NAME = "jarvis_facts"

MAX_REPLY_CHARS_STORED = 600
DEFAULT_RECALL_K = 3
DEFAULT_FACTS_RECALL_K = 3

# recall()/recall_facts() over-fetch this many candidates per requested
# result before relevance-filtering, so dropping below-threshold matches
# doesn't leave fewer than k results when better ones exist further down
# the nearest-neighbor ranking than the exact top-k slice.
_OVER_FETCH_MULTIPLIER = 3


def _get_embedder():
    return get_embedder()


def _get_collection():
    client = get_client()
    return client.get_or_create_collection(COLLECTION_NAME)


def _get_facts_collection():
    client = get_client()
    return client.get_or_create_collection(FACTS_COLLECTION_NAME)


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _relevance_threshold() -> float:
    from config import CONFIG
    return CONFIG.get("memory_relevance_threshold", 0.35)


def _filter_by_relevance(query_embedding: list, documents: list, embeddings: list) -> list:
    """Drop nearest-neighbor results whose cosine similarity to the
    query falls below CONFIG["memory_relevance_threshold"].

    Missing/mismatched embeddings (an older Chroma result shape, a test
    double, etc.) degrade to returning `documents` unfiltered rather
    than silently dropping everything -- filtering out real memories on
    infrastructure grounds would be a worse failure mode than
    occasionally showing one that's a bit off-topic.
    """
    if not embeddings or len(embeddings) != len(documents):
        return documents

    return [
        doc
        for doc, emb in zip(documents, embeddings)
        if _cosine(query_embedding, emb) >= _relevance_threshold()
    ]


def remember_turn(user_message: str, assistant_reply: str) -> None:
    """Store one (user, assistant) turn for future semantic recall."""
    if not user_message or not assistant_reply:
        return

    # Creative projects are hard context boundaries. Their turns must not
    # enter the global conversation collection where another project can
    # later retrieve them by semantic similarity.
    if document_state.get_active_project():
        return

    text = (
        f"User asked: {user_message}\n"
        f"Jarvis answered: {assistant_reply[:MAX_REPLY_CHARS_STORED]}"
    )
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        collection = _get_collection()
        embedder = _get_embedder()
        embedding = embedder.encode(text).tolist()
        collection.add(
            documents=[text],
            embeddings=[embedding],
            ids=[f"turn::{timestamp}"],
            metadatas=[{"timestamp": timestamp}],
        )
    except Exception:
        pass


def recall(query: str, k: int = DEFAULT_RECALL_K, query_embedding: list = None) -> list:
    """Return up to k past turns semantically relevant to `query`.

    Global conversation memory is unavailable while a creative project is
    active. Creative retrieval must remain inside the project boundary.

    Over-fetches (k * _OVER_FETCH_MULTIPLIER) before relevance-filtering,
    since dropping below-threshold candidates can otherwise leave fewer
    than k results even when better matches exist further down the
    nearest-neighbor ranking.
    """
    if document_state.get_active_project():
        return []

    try:
        collection = _get_collection()
        count = collection.count()
        if count == 0:
            return []

        embedding = (
            query_embedding
            if query_embedding is not None
            else _get_embedder().encode(query).tolist()
        )
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(k * _OVER_FETCH_MULTIPLIER, count),
            include=["documents", "embeddings"],
        )
        documents = (results.get("documents") or [[]])[0]
        embeddings = (results.get("embeddings") or [[]])[0]
        return _filter_by_relevance(embedding, documents, embeddings)[:k]
    except Exception:
        return []


def remember_fact(category: str, fact: str) -> str:
    """Store a durable fact under a category."""
    category = (category or "other").strip().lower() or "other"
    fact = (fact or "").strip()
    if not fact:
        return "No fact given to remember."

    timestamp = datetime.now(timezone.utc).isoformat()
    text = f"[{category}] {fact}"

    try:
        collection = _get_facts_collection()
        embedder = _get_embedder()
        embedding = embedder.encode(text).tolist()
        collection.add(
            documents=[text],
            embeddings=[embedding],
            ids=[f"fact::{timestamp}"],
            metadatas=[{"timestamp": timestamp, "category": category}],
        )
        return f"Remembered ({category}): {fact}"
    except Exception as e:
        return f"Could not save that: {e}"


def recall_facts(query: str, k: int = DEFAULT_FACTS_RECALL_K, query_embedding: list = None) -> list:
    """Return up to k stored facts semantically relevant to `query`.

    Remembered facts are global, so they cannot safely be used as
    Creative Mode project context.
    """
    if document_state.get_active_project():
        return []

    try:
        collection = _get_facts_collection()
        count = collection.count()
        if count == 0:
            return []

        embedding = (
            query_embedding
            if query_embedding is not None
            else _get_embedder().encode(query).tolist()
        )
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(k * _OVER_FETCH_MULTIPLIER, count),
            include=["documents", "embeddings"],
        )
        documents = (results.get("documents") or [[]])[0]
        embeddings = (results.get("embeddings") or [[]])[0]
        return _filter_by_relevance(embedding, documents, embeddings)[:k]
    except Exception:
        return []


def list_facts(category: str = None) -> list:
    """Return all stored facts, optionally filtered to one category."""
    try:
        collection = _get_facts_collection()
        if collection.count() == 0:
            return []

        where = {"category": category.strip().lower()} if category else None
        results = collection.get(where=where) if where else collection.get()
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []

        paired = list(zip(documents, metadatas))
        paired.sort(key=lambda pair: pair[1].get("timestamp", ""))
        return [doc for doc, _ in paired]
    except Exception:
        return []


def forget_all() -> str:
    """Permanently clear all stored conversation memory and facts."""
    try:
        client = chromadb.PersistentClient(path=str(DB_PATH))
        for name in (COLLECTION_NAME, FACTS_COLLECTION_NAME):
            try:
                client.delete_collection(name)
            except Exception:
                pass
        return "Long-term memory cleared (conversations and remembered facts)."
    except Exception as e:
        return f"Could not clear memory: {e}"
