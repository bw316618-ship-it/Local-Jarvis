"""Regression test for stale active-document isolation."""

from pathlib import Path
from unittest.mock import patch

import memory.document_store as document_store
import memory.project_memory as project_memory
from tools import creative_generation
from voice import document_state


def test_stale_document_cannot_escape_active_project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    allowed = tmp_path / "chapters.pdf"
    stale = tmp_path / "old-crown.pdf"
    allowed.write_bytes(b"x")
    stale.write_bytes(b"x")

    project_memory.ensure_project("Crown")
    project_memory.add_document("Crown", str(allowed))
    document_state.set_active_project("Crown")

    # Simulate corrupted/stale runtime state.
    document_state.set_active_document(str(stale))

    with patch.object(
        creative_generation.document_store,
        "search",
        return_value={
            "documents": ["Crown canon"],
            "metadatas": [{"source": str(allowed.resolve())}],
        },
    ) as search:
        result = creative_generation.get_creative_context("plot")

    assert "Crown canon" in result
    assert search.call_args.kwargs["project"] == "Crown"
    assert "source" not in search.call_args.kwargs
    assert document_state.get_active_document() is None
