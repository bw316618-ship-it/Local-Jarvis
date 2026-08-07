import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader
from config import CONFIG
from memory import document_store

CHUNK_SIZE = CONFIG["index_chunk_size"]
CHUNK_OVERLAP = CONFIG["index_chunk_overlap"]


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def main(folder):
    state = document_store.load_state()
    indexed = skipped = failed = 0

    for path in Path(folder).rglob("*"):
        if path.suffix.lower() not in [".txt", ".md", ".pdf", ".py", ".js"]:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        key = str(path.resolve())
        if state.get(key) == mtime:
            skipped += 1
            continue

        print(f"Reading: {path}")
        try:
            text = read_text(path)
        except Exception as e:
            failed += 1
            print(f"Skipped {path}: {e}")
            continue

        n_chunks = document_store.index_one_file(
            path, text, document_store.MANUAL, CHUNK_SIZE, CHUNK_OVERLAP, state
        )
        indexed += 1
        print(f"Indexed {path.name} ({n_chunks} chunks)")

    document_store.save_state(state)
    print(f"Ingestion complete: {indexed} indexed, {skipped} unchanged, {failed} failed.")


if __name__ == "__main__":
    main(sys.argv[1])