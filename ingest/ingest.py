import sys
import json
import pathlib
from pathlib import Path

# ingest.py is meant to be run directly (`python ingest/ingest.py`), which
# puts ingest/ itself -- not the project root -- on sys.path[0]. Without
# this, `from config import CONFIG` below fails with ModuleNotFoundError
# since Python can't find a top-level `config` module from inside ingest/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader

from config import CONFIG
from memory.shared import get_embedder, get_client

CHUNK_SIZE = CONFIG["index_chunk_size"]
CHUNK_OVERLAP = CONFIG["index_chunk_overlap"]

BASE_DIR = Path(__file__).resolve().parent.parent

# Tracks path -> mtime for everything already ingested, the same pattern
# tools/file_index.py uses -- previously main() re-read, re-chunked, and
# re-embedded every single file on every run, even ones that hadn't
# changed since last time. On a knowledge base of any real size that's a
# lot of wasted embedding work for no benefit; this file is a separate
# state file (not tools/file_index.py's file_index_state.json) since the
# two indexers track different collections and different folders.
STATE_PATH = BASE_DIR / "memory" / "ingest_state.json"


def read_text(path: pathlib.Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str):
    words = text.split()
    if not words:
        return
    step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
    for i in range(0, len(words), step):
        yield " ".join(words[i:i + CHUNK_SIZE])


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def main(folder):
    embedder = get_embedder()
    client = get_client()
    collection = client.get_or_create_collection("jarvis_memory")
    state = _load_state()

    indexed = skipped_unchanged = failed = 0

    for path in pathlib.Path(folder).rglob("*"):
        if path.suffix.lower() not in [".txt", ".md", ".pdf", ".py", ".js"]:
            continue

        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        key = str(path.resolve())
        if state.get(key) == mtime:
            skipped_unchanged += 1
            continue

        print(f"Reading: {path}")
        try:
            text = read_text(path)
        except Exception as e:
            failed += 1
            print(f"Skipped {path}: {e}")
            continue

        # Clear any previously-indexed chunks for this file first, in case
        # it shrank and now has fewer chunks than its last version did --
        # same guard tools/file_index.py uses for the same reason.
        try:
            collection.delete(where={"source": key})
        except Exception:
            pass

        chunks = list(chunk_text(text))
        if chunks:
            # Batch-encode and batch-add all of a file's chunks in one
            # call each, instead of one encode()/add() round-trip per
            # chunk -- meaningfully faster for anything with a lot of
            # chunks (a long PDF can easily have dozens).
            embeddings = embedder.encode(chunks).tolist()
            ids = [f"{key}::{idx}" for idx in range(len(chunks))]
            metadatas = [{"source": key, "filename": path.name} for _ in chunks]
            collection.add(
                documents=chunks,
                embeddings=embeddings,
                ids=ids,
                metadatas=metadatas,
            )

        state[key] = mtime
        indexed += 1
        print(f"Indexed {path.name} ({len(chunks)} chunks)")

    _save_state(state)

    print(client.list_collections())
    results = collection.get()
    print("Stored IDs:", len(results["ids"]))
    print(
        f"Ingestion complete: {indexed} files indexed/updated, "
        f"{skipped_unchanged} unchanged (skipped), {failed} failed to read."
    )


if __name__ == "__main__":
    main(sys.argv[1])
