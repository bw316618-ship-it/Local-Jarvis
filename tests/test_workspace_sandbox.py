"""Workspace sandbox: read/write/delete must stay confined to workspace/,
even against path-traversal and absolute-path escape attempts."""

import tools.file_manager as fm


def test_normal_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "WORKSPACE_DIR", tmp_path)
    fm.write_file("notes/todo.txt", "buy milk")
    assert fm.read_file("notes/todo.txt") == "buy milk"


def test_relative_path_traversal_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "WORKSPACE_DIR", tmp_path)
    result = fm.read_file("../../../../etc/passwd")
    assert "outside the Jarvis workspace" in result


def test_absolute_path_is_confined_inside_the_sandbox(tmp_path, monkeypatch):
    """An absolute-looking path like '/etc/cron.d/evil' must land inside
    workspace/etc/cron.d/evil, never at the real /etc."""
    monkeypatch.setattr(fm, "WORKSPACE_DIR", tmp_path)
    fm.write_file("/etc/cron.d/evil", "malicious")

    assert (tmp_path / "etc" / "cron.d" / "evil").exists()
    assert not (tmp_path.parent / "etc").exists(), "must never escape to a real /etc-like path"


def test_delete_outside_workspace_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "WORKSPACE_DIR", tmp_path)
    result = fm.delete_file("../../outside.txt")
    assert "outside the Jarvis workspace" in result
