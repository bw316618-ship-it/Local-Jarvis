from pathlib import Path
import os

import chromadb
from sentence_transformers import SentenceTransformer


class JarvisMemory:
    def __init__(self):
        # Project root (jarvis/)
        BASE_DIR = Path(__file__).resolve().parent.parent

        # Absolute database path
        DB_PATH = BASE_DIR / "memory" / "chroma"

        print(f"Retriever CWD: {os.getcwd()}")
        print(f"Retriever file: {__file__}")
        print(f"Database path: {DB_PATH}")

        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

        self.client = chromadb.PersistentClient(
            path=str(DB_PATH)
        )

        print("Collections:", self.client.list_collections())

        self.collection = self.client.get_collection(
            name="jarvis_memory"
        )

    def search(self, query: str, k: int = 5):
        embedding = self.embedder.encode(query).tolist()

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=k
        )

        documents = results.get("documents", [[]])

        if not documents or len(documents[0]) == 0:
            return []

        return documents[0]