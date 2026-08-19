"""
Whole-computer semantic file search.

Indexes discovered files into the shared document store using
source_type="discovered". Manually curated ingest documents use
source_type="manual", so the two knowledge sources remain isolated
during retrieval.
"""

import json
from pathlib import Path

from pypdf import PdfReader

from config import CONFIG, get_index_roots
from memory import document_store
from memory.shared import get_embedder

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = document_store.STATE_PATH
DB_PATH = document_store.BASE_DIR / "memory" / "chroma"

CHUNK_SIZE = CONFIG["index_chunk_size"]
CHUNK_OVERLAP = CONFIG["index_chunk_overlap"]
MAX_FILE_MB = CONFIG["index_max_file_mb"]

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".json", ".csv", ".log",
    ".yml", ".yaml", ".ini", ".cfg",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
INDEXABLE_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS

SKIP_DIR_NAMES = {
    "node_modules", "__pycache__", ".git", "venv", ".venv",
    "site-packages", "$RECYCLE.BIN", "System Volume Information", ".cache",
}


def _get_embedder():
    return get_embedder()


def _get_collection():
    return document_store.get_collection()


def _load_state() -> dict:
    return document_store.load_state()


def _save_state(state: dict) -> None:
    document_store.save_state(state)


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


def _iter_candidate_files(roots):
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


def count_pending_changes(directories=None) -> int:
    """Count new/changed indexable files without indexing them."""
    roots = directories if directories is not None else get_index_roots()
    state = _load_state()
    pending = 0

    for path in _iter_candidate_files(roots):
        key = str(path.resolve())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        if state.get(key) != mtime:
            pending += 1

    return pending


def index_files(directories=None, progress=None) -> str:
    """Index new/changed discovered files."""
    roots = directories if directories is not None else get_index_roots()
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
            n_chunks = document_store.index_one_file(
                path=path,
                text=text,
                source_type=document_store.DISCOVERED,
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                state=state,
            )
        except Exception as e:
            failed += 1
            if progress:
                progress(f"Skipped {path.name}: {e}")
            continue

        indexed += 1

        if progress:
            progress(f"Indexed {path.name} ({n_chunks} chunks)")

    _save_state(state)

    return (
        f"Indexing complete: {indexed} files indexed/updated, "
        f"{skipped_unchanged} unchanged (skipped), {failed} failed to read."
    )


def search_files(query: str, k: int = 5) -> str:
    """Semantically search only discovered whole-computer files."""
    result = document_store.search(
        query,
        source_type=document_store.DISCOVERED,
        k=k,
    )

    documents = result["documents"]
    metadatas = result["metadatas"]

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
                "(Documents, Desktop, Downloads by default). Finds files by "
                "meaning/content, not just filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for.",
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
                "Index new or changed files under the configured indexing "
                "folders so they become searchable via search_files."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

FILE_INDEX_FUNCTIONS = {
    "search_files": search_files,
    "index_files": index_files,
}
