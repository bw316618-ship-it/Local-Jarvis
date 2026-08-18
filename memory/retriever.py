from memory import document_store
from memory.shared import get_embedder, get_client


class JarvisMemory:
    def __init__(self):
        # Both the embedder and the ChromaDB client are shared singletons
        # (see memory/shared.py) so this doesn't load its own separate
        # copy of the embedding model if another module already has.
        self.embedder = get_embedder()
        self.client = get_client()

        # Use the shared document store collection for indexed documents.
        self.collection = document_store.get_collection()

    def search(self, query: str, k: int = 5, query_embedding: list = None):
        return document_store.search(
            query,
            source_type=document_store.MANUAL,
            k=k,
            query_embedding=query_embedding,
        )["documents"]
