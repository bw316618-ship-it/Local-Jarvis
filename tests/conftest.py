"""
Shared fixtures for the Jarvis test suite.

The heavy ML dependencies (chromadb, sentence_transformers, ollama) are
mocked at collection time, session-wide -- so `pytest` runs fast and
doesn't require a multi-GB torch install just to verify logic. Tests that
need real embedding/chat behavior aren't in scope here; this suite
targets the *logic* around those calls (sandboxing, incremental
indexing, confirmation gating, chunking, pattern detection, etc.), which
is both the highest-risk code and fully testable without the real models.
"""

import sys
from unittest.mock import MagicMock

import pytest

# Must happen before any project module that imports these gets collected.
sys.modules.setdefault("chromadb", MagicMock())
sys.modules.setdefault("sentence_transformers", MagicMock())
sys.modules.setdefault("ollama", MagicMock())


@pytest.fixture(autouse=True)
def never_touch_real_project_files(tmp_path, monkeypatch):
    """Safety net, on top of individual tests mocking their own paths:
    redirect every module-level path Jarvis writes real data to, so a
    test that forgets to mock one of these can never pollute the actual
    project's memory/ directory (audit log, chroma DB, transcripts, etc.)
    just by calling a function that happens to log or persist something
    as a side effect.
    """
    import memory.audit_log as audit_log
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")

    import memory.transcript as transcript
    monkeypatch.setattr(transcript, "TRANSCRIPTS_DIR", tmp_path / "transcripts")


@pytest.fixture
def tmp_project_dir(tmp_path):
    """A throwaway directory standing in for a project/workspace root."""
    return tmp_path


@pytest.fixture
def fake_embedder():
    """A mock embedder whose .encode(x).tolist() returns a fixed-size
    vector per input, matching real SentenceTransformer's batch shape."""
    embedder = MagicMock()

    def _encode(x):
        if isinstance(x, str):
            return MagicMock(tolist=lambda: [0.1, 0.2])
        return MagicMock(tolist=lambda: [[0.1, 0.2] for _ in x])

    embedder.encode.side_effect = _encode
    return embedder


@pytest.fixture
def fake_collection():
    """A mock ChromaDB collection with sane defaults."""
    collection = MagicMock()
    collection.count.return_value = 0
    return collection
