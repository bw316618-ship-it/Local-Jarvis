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
than only finding them via semantic search. Jarvis calls remember_fact
as a tool when something like this comes up in conversation.

Both use the same retrieval pattern as the other memory stores: semantic
search (the top few relevant entries for whatever you're asking now), not
a full dump -- the local model's context window is too small for that,
and most stored history wouldn't be relevant to the current question.
"""

from datetime import datetime, timezone
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"
COLLECTION_NAME = "jarvis_conversations"
FACTS_COLLECTION_NAME = "jarvis_facts"

MAX_REPLY_CHARS_STORED = 600  # keep stored entries compact
DEFAULT_RECALL_K = 3
DEFAULT_FACTS_RECALL_K = 3

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _get_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(COLLECTION_NAME)


def _get_facts_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(FACTS_COLLECTION_NAME)


def remember_turn(user_message: str, assistant_reply: str) -> None:
    """Store one (user, assistant) turn for future semantic recall.

    Failures here are swallowed rather than raised -- memory is a nice-to-
    have, and a storage hiccup should never take down an actual reply the
    user is waiting on.
    """
    if not user_message or not assistant_reply:
        return

    text = f"User asked: {user_message}\nJarvis answered: {assistant_reply[:MAX_REPLY_CHARS_STORED]}"
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


def recall(query: str, k: int = DEFAULT_RECALL_K) -> list:
    """Return up to k past turns semantically relevant to `query`."""
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []

        embedder = _get_embedder()
        embedding = embedder.encode(query).tolist()
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(k, collection.count()),
        )
        return (results.get("documents") or [[]])[0]
    except Exception:
        return []


def remember_fact(category: str, fact: str) -> str:
    """Store a durable fact under a category (e.g. 'person', 'preference',
    'project'). Unlike remember_turn, this is explicit and tool-driven --
    called when something worth remembering long-term comes up, not
    automatically after every message.
    """
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


def recall_facts(query: str, k: int = DEFAULT_FACTS_RECALL_K) -> list:
    """Return up to k stored facts semantically relevant to `query`."""
    try:
        collection = _get_facts_collection()
        if collection.count() == 0:
            return []

        embedder = _get_embedder()
        embedding = embedder.encode(query).tolist()
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(k, collection.count()),
        )
        return (results.get("documents") or [[]])[0]
    except Exception:
        return []


def list_facts(category: str = None) -> list:
    """Return all stored facts, optionally filtered to one category --
    for direct inspection (e.g. '/memory people'), not semantic search."""
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
                pass  # fine if it never existed
        return "Long-term memory cleared (conversations and remembered facts)."
    except Exception as e:
        return f"Could not clear memory: {e}"
