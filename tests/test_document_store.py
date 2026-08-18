"""Shared document chunking: short/empty/long text splitting behavior.

Used by both ingest/ingest.py and tools/file_index.py, which previously
each had their own near-identical copy of this logic (tools/file_index.py's
_chunk_text). These tests moved here, targeting the one real
implementation, when that duplication was removed."""

from memory.document_store import chunk_text

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def test_chunk_text_short_text_is_one_chunk():
    chunks = list(chunk_text("one two three four five", CHUNK_SIZE, CHUNK_OVERLAP))
    assert chunks == ["one two three four five"]


def test_chunk_text_empty_yields_nothing():
    assert list(chunk_text("", CHUNK_SIZE, CHUNK_OVERLAP)) == []


def test_chunk_text_long_text_splits_with_overlap():
    long_text = " ".join(f"word{i}" for i in range(1200))
    chunks = list(chunk_text(long_text, CHUNK_SIZE, CHUNK_OVERLAP))
    sizes = [len(c.split()) for c in chunks]
    assert sizes == [500, 500, 300]
