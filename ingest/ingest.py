print("RUNNING INGEST.PY")
import sys
import pathlib
from pathlib import Path
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import chromadb
import os

print("Current working directory:", os.getcwd())
print("This file:", __file__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"

def read_text(path: pathlib.Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        return path.read_text(encoding="utf-8", errors="ignore")

def chunk_text(text: str):
    words = text.split()
    for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
        yield " ".join(words[i:i + CHUNK_SIZE])

def main(folder):
    model = SentenceTransformer("all-MiniLM-L6-v2")

    client = chromadb.PersistentClient(
        path=str(DB_PATH)
    )

    collection = client.get_or_create_collection("jarvis_memory")

    for path in pathlib.Path(folder).rglob("*"):
        print(path)
        if path.suffix.lower() not in [".txt", ".md", ".pdf", ".py", ".js"]:
            continue

        try:
            text = read_text(path)
            print(f"Reading: {path}")
            for idx, chunk in enumerate(chunk_text(text)):
                embedding = model.encode(chunk).tolist()
                collection.add(
                    documents=[chunk],
                    embeddings=[embedding],
                    ids=[f"{path}_{idx}"]
                )
                print(f"Added chunk {idx} from {path}")
        except Exception as e:
            print(f"Skipped {path}: {e}")
    print(client.list_collections())

    results = collection.get()
    print("Stored IDs:", len(results["ids"]))

    print("Ingestion complete.")

if __name__ == "__main__":
    main(sys.argv[1])