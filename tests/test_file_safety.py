"""File safety: rename/move/organize correctness, including a permanent
regression test for the move_file bug found during development (guessing
'is this a directory' from an already-existing path fails for the common
case of moving into a not-yet-created folder)."""

from pathlib import Path

from tools.full_access_files import rename_file, move_file, organize_directory


def test_rename_file(tmp_path):
    (tmp_path / "draft.txt").write_text("hello")
    result = rename_file(str(tmp_path / "draft.txt"), "final.txt")
    assert (tmp_path / "final.txt").exists()
    assert not (tmp_path / "draft.txt").exists()
    assert "Renamed" in result


def test_rename_refuses_to_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = rename_file(str(tmp_path / "a.txt"), "b.txt")
    assert "already exists" in result
    assert (tmp_path / "a.txt").exists(), "original must survive a refused rename"


def test_rename_rejects_path_traversal_in_new_name(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    result = rename_file(str(tmp_path / "a.txt"), "../escape.txt")
    assert "plain filename" in result
    assert (tmp_path / "a.txt").exists()


def test_move_into_a_directory_that_does_not_exist_yet(tmp_path):
    """Regression test: the first implementation guessed 'is this a
    directory?' by checking Path.is_dir() on the destination, which is
    only true if the directory already exists -- so moving into a brand
    new folder silently created a *file* named after the folder instead
    of a directory containing the moved file."""
    (tmp_path / "final.txt").write_text("data")
    new_dir = tmp_path / "archive"

    result = move_file(str(tmp_path / "final.txt"), str(new_dir))

    assert new_dir.is_dir(), "destination must become an actual directory"
    assert (new_dir / "final.txt").exists(), "file must land inside it, keeping its name"
    assert not (tmp_path / "final.txt").exists()
    assert "Moved" in result


def test_move_into_an_existing_directory(tmp_path):
    existing = tmp_path / "archive"
    existing.mkdir()
    (tmp_path / "c.txt").write_text("data")

    move_file(str(tmp_path / "c.txt"), str(existing))
    assert (existing / "c.txt").exists()


def test_move_with_rename_in_one_step(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    move_file(str(tmp_path / "a.txt"), str(tmp_path / "renamed"), new_name="b.txt")
    assert (tmp_path / "renamed" / "b.txt").exists()


def test_move_refuses_when_destination_is_actually_a_file(tmp_path):
    (tmp_path / "not_a_dir.txt").write_text("x")
    (tmp_path / "d.txt").write_text("data")

    result = move_file(str(tmp_path / "d.txt"), str(tmp_path / "not_a_dir.txt"))

    assert "not a directory" in result
    assert (tmp_path / "d.txt").exists(), "source must be untouched when destination is invalid"


def test_organize_directory_categorizes_by_type(tmp_path):
    (tmp_path / "photo1.jpg").write_bytes(b"x")
    (tmp_path / "photo2.PNG").write_bytes(b"x")  # uppercase extension
    (tmp_path / "report.pdf").write_bytes(b"x")
    (tmp_path / "budget.xlsx").write_bytes(b"x")
    (tmp_path / "script.py").write_bytes(b"x")
    (tmp_path / "mystery.xyz").write_bytes(b"x")  # unknown extension

    organize_directory(str(tmp_path))

    assert (tmp_path / "images" / "photo1.jpg").exists()
    assert (tmp_path / "images" / "photo2.PNG").exists(), "extension matching must be case-insensitive"
    assert (tmp_path / "documents" / "report.pdf").exists()
    assert (tmp_path / "spreadsheets" / "budget.xlsx").exists()
    assert (tmp_path / "code" / "script.py").exists()
    assert (tmp_path / "other" / "mystery.xyz").exists(), "unknown extensions should land in 'other', not error out"


def test_organize_directory_does_not_touch_existing_subfolders(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "inner.txt").write_text("should stay put")
    (tmp_path / "photo.jpg").write_bytes(b"x")

    organize_directory(str(tmp_path))

    assert (notes / "inner.txt").exists(), "pre-existing subfolders must not be recursed into or disturbed"


def test_organize_directory_is_idempotent(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"x")
    organize_directory(str(tmp_path))
    result = organize_directory(str(tmp_path))
    assert "0 file(s) moved" in result, "running twice should be a no-op, not an error or a re-shuffle"
