"""File indexer: discovery/filtering (including SKIP_DIR_NAMES pruning),
the self-indexing collision guard, incremental indexing, batched
embedding, and that search_files only ever searches "discovered" files
(not manually-ingested ones sharing the same collection)."""

import os
import time
from unittest.mock import MagicMock

import tools.file_index as fi
from memory import document_store


def _patch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(fi, "DB_PATH", tmp_path / "chroma")


def test_file_discovery_filters_correctly(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()

    (root / "notes.txt").write_text("indexable")
    (root / "skip_me.exe").write_bytes(b"binary")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.txt").write_text("skip")
    big = root / "huge.txt"
    big.write_text("x" * (fi.MAX_FILE_MB * 1024 * 1024 + 1))

    found = sorted(p.name for p in fi._iter_candidate_files([str(root)]))

    assert "notes.txt" in found
    assert "skip_me.exe" not in found
    assert "ignored.txt" not in found
    assert "huge.txt" not in found


def test_skipped_directories_are_pruned_not_just_filtered(tmp_path, monkeypatch):
    """SKIP_DIR_NAMES folders must never be descended into at all -- the
    old rglob()-based version filtered them out after the fact, which
    means rglob had already recursed into (and stat'd every file inside)
    a node_modules tree before the results were discarded. Checking only
    the final output (a file inside node_modules is absent) doesn't
    distinguish "pruned before descending" from "filtered afterward" --
    both give the same output -- so this spies on os.walk itself to
    confirm node_modules is never even visited."""
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    deep = root / "node_modules" / "some_pkg" / "lib"
    deep.mkdir(parents=True)
    (deep / "readme.md").write_text("this should never be seen")

    visited_dirs = []
    real_walk = os.walk

    def spying_walk(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited_dirs.append(dirpath)
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(fi.os, "walk", spying_walk)

    found = list(fi._iter_candidate_files([str(root)]))

    assert found == []
    assert not any("node_modules" in d for d in visited_dirs), (
        "node_modules should be pruned before os.walk descends into it, not just filtered afterward"
    )


def test_indexer_never_indexes_its_own_state_file(tmp_path, monkeypatch):
    """If the state file happens to live inside a directory being indexed,
    it must never index itself -- otherwise its own changing timestamp
    would make it 're-index' forever."""
    root = tmp_path / "collision_root"
    root.mkdir()
    monkeypatch.setattr(fi, "STATE_PATH", root / "state.json")
    monkeypatch.setattr(fi, "DB_PATH", root / "chroma")

    (root / "c.txt").write_text("gamma content")

    found = list(fi._iter_candidate_files([str(root)]))
    fi._save_state({})  # creates state.json inside root, mimicking real usage

    found_after = [p.name for p in fi._iter_candidate_files([str(root)])]
    assert "state.json" not in found_after


def test_incremental_indexing_skips_unchanged_files(tmp_path, monkeypatch, fake_collection, fake_embedder):
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("alpha")
    (root / "b.txt").write_text("beta")

    monkeypatch.setattr(document_store, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)

    fi.index_files(directories=[str(root)])
    assert fake_collection.add.call_count == 2
    fake_collection.add.reset_mock()

    fi.index_files(directories=[str(root)])
    assert fake_collection.add.call_count == 0, "unchanged files must not be re-embedded/re-added"


def test_incremental_indexing_reindexes_only_the_changed_file(tmp_path, monkeypatch, fake_collection, fake_embedder):
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("alpha")
    (root / "b.txt").write_text("beta")

    monkeypatch.setattr(document_store, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)

    fi.index_files(directories=[str(root)])
    time.sleep(0.02)
    (root / "a.txt").write_text("alpha CHANGED")
    fake_collection.add.reset_mock()

    fi.index_files(directories=[str(root)])
    assert fake_collection.add.call_count == 1


def test_indexed_chunks_are_tagged_discovered(tmp_path, monkeypatch, fake_collection, fake_embedder):
    """Regression test: index_files() previously hand-rolled its own
    write path instead of going through document_store.index_one_file(),
    and never set the source_type metadata tag at all -- silently
    breaking search_files()'s ability to filter manual vs. discovered
    documents apart in the shared collection."""
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("alpha")

    monkeypatch.setattr(document_store, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)

    fi.index_files(directories=[str(root)])

    metadatas = fake_collection.add.call_args.kwargs["metadatas"]
    assert all(m["source_type"] == document_store.DISCOVERED for m in metadatas)


def test_embedding_and_add_are_batched_per_file_not_per_chunk(tmp_path, monkeypatch, fake_collection, fake_embedder):
    """encode() and collection.add() should each be called once per file,
    not once per chunk -- multiple small add() calls per file would be a
    performance regression."""
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    long_text = " ".join(f"word{i}" for i in range(1200))  # -> 3 chunks
    (root / "big.txt").write_text(long_text)

    monkeypatch.setattr(document_store, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)

    fi.index_files(directories=[str(root)])

    assert fake_embedder.encode.call_count == 1
    assert fake_collection.add.call_count == 1
    call_kwargs = fake_collection.add.call_args.kwargs
    assert len(call_kwargs["documents"]) == 3
    assert len(call_kwargs["embeddings"]) == 3
    assert len(call_kwargs["ids"]) == 3


def test_count_pending_changes_tracks_the_indexing_lifecycle(tmp_path, monkeypatch, fake_collection, fake_embedder):
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("alpha")
    (root / "b.txt").write_text("beta")

    assert fi.count_pending_changes(directories=[str(root)]) == 2

    monkeypatch.setattr(document_store, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)
    fi.index_files(directories=[str(root)])

    assert fi.count_pending_changes(directories=[str(root)]) == 0

    time.sleep(0.02)
    (root / "a.txt").write_text("alpha CHANGED")
    (root / "c.txt").write_text("new file")

    assert fi.count_pending_changes(directories=[str(root)]) == 2


def test_search_files_only_searches_discovered_documents(monkeypatch, fake_embedder):
    """Regression test for the same source_type bug from the other side:
    search_files() must filter to "discovered" documents, or manually-
    ingested content (via ingest/ingest.py) sharing the same collection
    would leak into whole-computer file search results."""
    collection = MagicMock()
    collection.count.return_value = 3
    collection.query.return_value = {
        "documents": [["some text"]],
        "metadatas": [[{"source": "x", "filename": "x.txt", "source_type": "discovered"}]],
    }
    monkeypatch.setattr(document_store, "get_collection", lambda: collection)
    monkeypatch.setattr(document_store, "get_embedder", lambda: fake_embedder)

    fi.search_files("anything")

    assert collection.query.call_args.kwargs["where"] == {"source_type": document_store.DISCOVERED}


def test_search_files_reports_when_nothing_indexed_yet(monkeypatch):
    collection = MagicMock()
    collection.count.return_value = 0
    monkeypatch.setattr(document_store, "get_collection", lambda: collection)

    result = fi.search_files("anything")

    assert "index your files" in result.lower()
