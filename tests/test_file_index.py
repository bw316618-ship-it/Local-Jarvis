"""File indexer: chunking, discovery/filtering, incremental indexing,
the self-indexing collision guard, and batched embedding."""

import time
from pathlib import Path

import tools.file_index as fi


def _patch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(fi, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(fi, "DB_PATH", tmp_path / "chroma")


def test_chunk_text_short_text_is_one_chunk():
    chunks = list(fi._chunk_text("one two three four five"))
    assert chunks == ["one two three four five"]


def test_chunk_text_empty_yields_nothing():
    assert list(fi._chunk_text("")) == []


def test_chunk_text_long_text_splits_with_overlap():
    long_text = " ".join(f"word{i}" for i in range(1200))
    chunks = list(fi._chunk_text(long_text))
    sizes = [len(c.split()) for c in chunks]
    assert sizes == [500, 500, 300]


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

    monkeypatch.setattr(fi, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(fi, "_get_embedder", lambda: fake_embedder)

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

    monkeypatch.setattr(fi, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(fi, "_get_embedder", lambda: fake_embedder)

    fi.index_files(directories=[str(root)])
    time.sleep(0.02)
    (root / "a.txt").write_text("alpha CHANGED")
    fake_collection.add.reset_mock()

    fi.index_files(directories=[str(root)])
    assert fake_collection.add.call_count == 1


def test_embedding_and_add_are_batched_per_file_not_per_chunk(tmp_path, monkeypatch, fake_collection, fake_embedder):
    """encode() and collection.add() should each be called once per file,
    not once per chunk -- multiple small add() calls per file would be a
    performance regression."""
    _patch_state(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    long_text = " ".join(f"word{i}" for i in range(1200))  # -> 3 chunks
    (root / "big.txt").write_text(long_text)

    monkeypatch.setattr(fi, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(fi, "_get_embedder", lambda: fake_embedder)

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

    monkeypatch.setattr(fi, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(fi, "_get_embedder", lambda: fake_embedder)
    fi.index_files(directories=[str(root)])

    assert fi.count_pending_changes(directories=[str(root)]) == 0

    time.sleep(0.02)
    (root / "a.txt").write_text("alpha CHANGED")
    (root / "c.txt").write_text("new file")

    assert fi.count_pending_changes(directories=[str(root)]) == 2
