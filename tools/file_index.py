"""
Whole-computer semantic file search.

Unlike ingest/ingest.py (which builds Jarvis's manually-curated knowledge
base in the 'jarvis_memory' collection), this indexes real files on disk
into a separate 'jarvis_files' collection -- so Jarvis can find things
like "the PDF where I wrote about binary trees" without you first running
ingest.py on that specific file.

Indexing is incremental: each file's path + modified time is tracked in a
small JSON state file (memory/file_index_state.json), so re-running the
indexer only processes files that are new or changed, not everything from
scratch every time.

Both tools here are read-only from the perspective of your files (index_files
only creates embeddings in Jarvis's own database; it never modifies
anything on disk), so neither is registered as risky.
"""

import json
from pathlib import Path

import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "memory" / "chroma"
STATE_PATH = BASE_DIR / "memory" / "file_index_state.json"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
MAX_FILE_MB = 20  # skip absurdly large files rather than choke on them

TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".json", ".csv", ".log", ".yml", ".yaml", ".ini", ".cfg"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
INDEXABLE_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS

DEFAULT_ROOTS = [
    str(Path.home() / "Documents"),
    str(Path.home() / "Desktop"),
    str(Path.home() / "Downloads"),
]

# Folders that are noisy, huge, or not meaningful to search -- skip entirely.
SKIP_DIR_NAMES = {
    "node_modules", "__pycache__", ".git", "venv", ".venv", "site-packages",
    "$RECYCLE.BIN", "System Volume Information", ".cache",
}

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _get_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection("jarvis_files")


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


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix in DOCX_EXTENSIONS:
        try:
            import docx
        except ImportError as e:
            raise RuntimeError(
                "python-docx is required to index .docx files. "
                "Run: pip install -r requirements.txt"
            ) from e
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)

    return path.read_text(encoding="utf-8", errors="ignore")


def _chunk_text(text: str):
    words = text.split()
    if not words:
        return
    step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
    for i in range(0, len(words), step):
        yield " ".join(words[i:i + CHUNK_SIZE])


def _iter_candidate_files(roots):
    # Never index Jarvis's own bookkeeping files, even if a caller passes
    # directories that happen to include the project folder itself --
    # otherwise the state file changes on every save and never matches,
    # causing it to be "re-indexed" every single run forever.
    excluded = {STATE_PATH.resolve(), DB_PATH.resolve()}

    for root in roots:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in excluded or any(ex in resolved.parents for ex in excluded):
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path


def index_files(directories=None, progress=None) -> str:
    """Index (or re-index changed) files under `directories` for semantic search.

    `directories` defaults to Documents/Desktop/Downloads if not given.
    `progress`, if provided, is called with a status string after each file --
    lets the CLI show live progress without this module knowing about rich.
    """
    roots = directories or DEFAULT_ROOTS
    collection = _get_collection()
    embedder = _get_embedder()
    state = _load_state()

    indexed = skipped_unchanged = failed = 0

    for path in _iter_candidate_files(roots):
        key = str(path.resolve())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        if state.get(key) == mtime:
            skipped_unchanged += 1
            continue

        try:
            text = _extract_text(path)
        except Exception as e:
            failed += 1
            if progress:
                progress(f"Skipped {path.name}: {e}")
            continue

        # Clear any previously-indexed chunks for this file first, in case
        # it shrank and now has fewer chunks than its last version did.
        try:
            collection.delete(where={"source": key})
        except Exception:
            pass

        chunks = list(_chunk_text(text))
        for idx, chunk in enumerate(chunks):
            embedding = embedder.encode(chunk).tolist()
            collection.add(
                documents=[chunk],
                embeddings=[embedding],
                ids=[f"{key}::{idx}"],
                metadatas=[{"source": key, "filename": path.name}],
            )

        state[key] = mtime
        indexed += 1
        if progress:
            progress(f"Indexed {path.name} ({len(chunks)} chunks)")

    _save_state(state)

    return (
        f"Indexing complete: {indexed} files indexed/updated, "
        f"{skipped_unchanged} unchanged (skipped), {failed} failed to read."
    )


def search_files(query: str, k: int = 5) -> str:
    """Semantically search indexed files and return matching paths + snippets."""
    collection = _get_collection()
    if collection.count() == 0:
        return "No files have been indexed yet. Ask Jarvis to index your files first."

    embedder = _get_embedder()
    embedding = embedder.encode(query).tolist()

    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(k, collection.count()),
    )

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]

    if not documents:
        return f"No matching files found for '{query}'."

    lines = []
    seen_sources = set()
    for doc, meta in zip(documents, metadatas):
        source = meta.get("source", "unknown")
        if source in seen_sources:
            continue
        seen_sources.add(source)
        snippet = doc[:200].strip().replace("\n", " ")
        lines.append(f'- {source}\n  "{snippet}..."')

    return "Matching files:\n" + "\n".join(lines)


FILE_INDEX_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Semantically search files already indexed on this machine "
                "(Documents, Desktop, Downloads by default) -- finds files by "
                "meaning/content, not just filename. Use this when asked to "
                "find a document, PDF, note, or file by what it's about "
                "rather than its exact name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, e.g. 'notes about binary trees'.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "index_files",
            "description": (
                "(Re)index files under the default folders (Documents, Desktop, "
                "Downloads) so they become searchable via search_files. Only "
                "processes files that are new or changed since last time, so "
                "it's safe to call repeatedly. Can take a while the first time."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

FILE_INDEX_FUNCTIONS = {
    "search_files": search_files,
    "index_files": index_files,
}
