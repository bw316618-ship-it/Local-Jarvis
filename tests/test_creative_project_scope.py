"""Regression tests for strict Creative Mode project/document scoping.

These tests verify the public `project=` interface rather than requiring
callers to construct the internal source allowlist themselves. The hard
allowlist is enforced inside memory.document_store.search().
"""

from unittest.mock import patch

import memory.document_store as document_store
import memory.project_memory as project_memory
from tools import creative_generation, creative_tools
from voice import document_state


def setup_function():
    document_state.clear_scope()


def teardown_function():
    document_state.clear_scope()


def test_switching_to_project_clears_stale_document(tmp_path, monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    stale = tmp_path / "stale.pdf"
    stale.write_bytes(b"x")
    document_state.set_active_document(str(stale))

    result = creative_tools.set_creative_project("Crown")

    assert "Creative project active: 'Crown'" in result
    assert document_state.get_active_project() == "Crown"
    assert document_state.get_active_document() is None


def test_project_search_uses_project_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    allowed = tmp_path / "allowed.pdf"
    allowed.write_bytes(b"x")

    project_memory.ensure_project("Crown")
    project_memory.add_document("Crown", str(allowed))
    document_state.set_active_project("Crown")

    with patch.object(
        creative_tools.document_store,
        "search",
        return_value={
            "documents": ["Crown canon"],
            "metadatas": [{"source": str(allowed.resolve())}],
        },
    ) as search:
        result = creative_tools.search_creative_project("basic plot")

    assert "Crown canon" in result
    assert search.call_args.kwargs["source_type"] == document_store.MANUAL
    assert search.call_args.kwargs["project"] == "Crown"


def test_generation_uses_project_scope_when_no_document_selected(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    allowed = tmp_path / "chapters.pdf"
    allowed.write_bytes(b"x")

    project_memory.ensure_project("Crown")
    project_memory.add_document("Crown", str(allowed))
    document_state.set_active_project("Crown")

    with patch.object(
        creative_generation.document_store,
        "search",
        return_value={
            "documents": ["Crown story"],
            "metadatas": [{"source": str(allowed.resolve())}],
        },
    ) as search:
        result = creative_generation.get_creative_context("basic plot")

    assert "Crown story" in result
    assert search.call_args.kwargs["project"] == "Crown"
    assert "source" not in search.call_args.kwargs


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

    # The stale document is rejected before retrieval. Generation therefore
    # falls back to the project's registered-document scope.
    assert "Crown canon" in result
    assert search.call_args.kwargs["project"] == "Crown"
    assert "source" not in search.call_args.kwargs
    assert document_state.get_active_document() is None


def test_document_selection_rejects_unregistered_project_document(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"x")

    project_memory.ensure_project("Crown")
    document_state.set_active_project("Crown")

    result = creative_tools.set_creative_document(str(outside))

    assert "not registered" in result
    assert document_state.get_active_document() is None


def test_document_store_project_scope_is_registered_path_allowlist(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    allowed = tmp_path / "allowed.pdf"
    outside = tmp_path / "outside.pdf"
    allowed.write_bytes(b"x")
    outside.write_bytes(b"x")

    project_memory.ensure_project("Crown")
    project_memory.add_document("Crown", str(allowed))

    class FakeCollection:
        def count(self):
            return 2

        def query(self, **kwargs):
            self.kwargs = kwargs
            return {
                "documents": [["Crown canon"]],
                "metadatas": [[{"source": str(allowed.resolve())}]],
            }

    fake_collection = FakeCollection()

    with (
        patch.object(
            document_store,
            "get_collection",
            return_value=fake_collection,
        ),
        patch.object(
            document_store,
            "get_embedder",
        ) as get_embedder,
    ):
        get_embedder.return_value.encode.return_value.tolist.return_value = [
            0.0
        ]

        result = document_store.search(
            "basic plot",
            source_type=document_store.MANUAL,
            project="Crown",
        )

    assert result["documents"] == ["Crown canon"]

    where = fake_collection.kwargs["where"]
    assert "$and" in where

    source_condition = next(
        condition
        for condition in where["$and"]
        if "source" in condition
    )

    assert source_condition["source"]["$in"] == [str(allowed.resolve())]
    assert str(outside.resolve()) not in source_condition["source"]["$in"]


def test_document_store_empty_project_search_returns_nothing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    project_memory.ensure_project("Empty")

    class FakeCollection:
        def count(self):
            return 1

    with patch.object(
        document_store,
        "get_collection",
        return_value=FakeCollection(),
    ):
        result = document_store.search(
            "anything",
            source_type=document_store.MANUAL,
            project="Empty",
        )

    assert result == {"documents": [], "metadatas": []}
