"""
Shared singletons for the embedding model and ChromaDB client.

Several modules -- memory/retriever.py, memory/conversation_memory.py,
tools/file_index.py, and ingest/ingest.py -- each need a
SentenceTransformer embedder and a ChromaDB PersistentClient pointed at
the same on-disk database (memory/chroma/). Previously each one created
its own copy independently, which meant a single Jarvis process could
load the same embedding model into memory two or three times over, and
re-pay that load cost at startup for each one separately.

This module gives every caller the same lazily-created embedder and the
same PersistentClient, so the model is loaded (and the DB connection
opened) once per process no matter how many places end up needing it.

Note: memory/conversation_memory.py's forget_all() deliberately does NOT
go through get_client() here -- it's a rare, destructive one-off
operation (deleting whole collections), and keeping it on its own
PersistentClient call avoids any chance of that interacting oddly with
the shared, long-lived client used everywhere else.
"""

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

_embedder = None
_client = None


def get_embedder() -> SentenceTransformer:
    """Return the shared SentenceTransformer, creating it on first use."""
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder


def get_client() -> chromadb.PersistentClient:
    """Return the shared ChromaDB PersistentClient, creating it on first use."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(DB_PATH))
    return _client
