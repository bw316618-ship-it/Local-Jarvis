from memory.shared import get_embedder, get_client


class JarvisMemory:
    def __init__(self):
        # Both the embedder and the ChromaDB client are shared singletons
        # (see memory/shared.py) so this doesn't load its own separate
        # copy of the embedding model if another module already has.
        self.embedder = get_embedder()
        self.client = get_client()

        # get_or_create_collection avoids a crash on first run, before
        # ingest.py has ever been executed and the collection exists.
        self.collection = self.client.get_or_create_collection(
            name="jarvis_memory"
        )

    def search(self, query: str, k: int = 5):
        # Nothing has been ingested yet -- don't bother querying.
        if self.collection.count() == 0:
            return []

        embedding = self.embedder.encode(query).tolist()

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(k, self.collection.count())
        )

        documents = results.get("documents", [[]])

        if not documents or len(documents[0]) == 0:
            return []

        return documents[0]
