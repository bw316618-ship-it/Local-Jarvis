"""
Long-term conversation memory for Jarvis.

Unlike memory/retriever.py (documents you've manually ingested) and
tools/file_index.py (files found on disk), this stores a compact record
of past conversation turns -- so Jarvis can recall an earlier decision,
where you left off on a project, or something you told it weeks ago,
across separate runs of the app.

Each user turn is stored as one chunk (the question + a trimmed version
of Jarvis's answer), embedded, and searched the same way as the other two
memory stores. Retrieval is semantic (the top few relevant past turns for
whatever you're asking now), not a full history dump -- the local model's
context window is too small to paste in everything that's ever been said,
and most of it wouldn't be relevant to the current question anyway.
"""

from datetime import datetime, timezone
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"
COLLECTION_NAME = "jarvis_conversations"

MAX_REPLY_CHARS_STORED = 600  # keep stored entries compact
DEFAULT_RECALL_K = 3

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _get_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(COLLECTION_NAME)


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


def forget_all() -> str:
    """Permanently clear all stored conversation memory."""
    try:
        client = chromadb.PersistentClient(path=str(DB_PATH))
        client.delete_collection(COLLECTION_NAME)
        return "Long-term conversation memory cleared."
    except Exception as e:
        return f"Could not clear memory: {e}"
