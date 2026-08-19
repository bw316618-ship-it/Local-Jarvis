"""Tests for Creative Mode document-scoped memory."""

from unittest.mock import patch

import tools.creative_tools as creative_tools
from voice import document_state


def setup_function():
    document_state.clear_active_document()


def teardown_function():
    document_state.clear_active_document()


def test_creative_registry_contains_document_operations():
    names = {
        item["function"]["name"]
        for item in creative_tools.CREATIVE_TOOL_SCHEMAS
    }

    assert names == {
        "set_creative_document",
        "ingest_creative_document",
        "get_creative_document",
        "clear_creative_document",
        "search_creative_document",
    }


def test_set_creative_document_selects_existing_story(tmp_path):
    story = tmp_path / "story.txt"
    story.write_text("Chapter one.", encoding="utf-8")

    result = creative_tools.set_creative_document(str(story))

    assert "Creative document set to" in result
    assert document_state.get_active_document() == str(story.resolve())


def test_set_creative_document_rejects_missing_file(tmp_path):
    result = creative_tools.set_creative_document(
        str(tmp_path / "missing.pdf")
    )

    assert "does not exist" in result
    assert document_state.get_active_document() is None


def test_ingest_indexes_as_manual_and_activates_document(tmp_path):
    story = tmp_path / "story.txt"
    story.write_text(
        "Arin enters the abandoned station. The clock has stopped.",
        encoding="utf-8",
    )

    fake_state = {}

    with patch.object(
        creative_tools.document_store,
        "load_state",
        return_value=fake_state,
    ), patch.object(
        creative_tools.document_store,
        "index_one_file",
        return_value=2,
    ) as index_one, patch.object(
        creative_tools.document_store,
        "save_state",
    ) as save_state:
        result = creative_tools.ingest_creative_document(str(story))

    assert "ingested" in result.lower()
    assert document_state.get_active_document() == str(story.resolve())

    args = index_one.call_args.args
    assert args[0] == story.resolve()
    assert args[1].startswith("Arin enters")
    assert args[2] == creative_tools.document_store.MANUAL
    assert args[5] is fake_state
    save_state.assert_called_once()


def test_ingest_extracts_pdf_text(tmp_path):
    # The previous test forgot to create the path. Production code correctly
    # rejects nonexistent files, so create an empty placeholder for the mock.
    story = tmp_path / "story.pdf"
    story.write_bytes(b"%PDF-placeholder")

    class FakePage:
        def extract_text(self):
            return "Arin enters the station."

    class FakeReader:
        def __init__(self, path):
            assert path == str(story)

        pages = [FakePage()]

    with patch(
        "pypdf.PdfReader",
        FakeReader,
    ), patch.object(
        creative_tools.document_store,
        "load_state",
        return_value={},
    ), patch.object(
        creative_tools.document_store,
        "index_one_file",
        return_value=1,
    ) as index_one, patch.object(
        creative_tools.document_store,
        "save_state",
    ):
        result = creative_tools.ingest_creative_document(str(story))

    assert "ingested" in result.lower()
    assert index_one.call_args.args[1] == "Arin enters the station."


def test_ingest_rejects_unsupported_file_type(tmp_path):
    story = tmp_path / "story.docx"
    story.write_bytes(b"not supported")

    result = creative_tools.ingest_creative_document(str(story))

    assert "Unsupported creative document type" in result


def test_get_active_document_reports_state(tmp_path):
    story = tmp_path / "story.md"
    story.write_text("# Story", encoding="utf-8")

    creative_tools.set_creative_document(str(story))

    assert str(story.resolve()) in creative_tools.get_creative_document()


def test_clear_creative_document_removes_state(tmp_path):
    story = tmp_path / "story.txt"
    story.write_text("Story", encoding="utf-8")

    creative_tools.set_creative_document(str(story))
    result = creative_tools.clear_creative_document()

    assert result == "Creative document cleared."
    assert document_state.get_active_document() is None


def test_search_requires_active_document():
    result = creative_tools.search_creative_document("Arin")

    assert "No creative document is active" in result


def test_search_is_exactly_scoped_to_active_document(tmp_path):
    story = tmp_path / "story.txt"
    story.write_text("Arin enters the station.", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("Arin is actually on the moon.", encoding="utf-8")

    document_state.set_active_document(str(story))

    with patch.object(
        creative_tools.document_store,
        "search",
        return_value={
            "documents": ["Arin enters the station."],
            "metadatas": [
                {
                    "source": str(story.resolve()),
                    "source_type": creative_tools.document_store.MANUAL,
                }
            ],
        },
    ) as search:
        result = creative_tools.search_creative_document("Arin")

    assert "Arin enters the station." in result
    assert "moon" not in result
    assert search.call_args.kwargs["source_type"] == creative_tools.document_store.MANUAL
    assert search.call_args.kwargs["source"] == str(story.resolve())


def test_search_does_not_fall_back_to_discovered_files(tmp_path):
    story = tmp_path / "story.txt"
    story.write_text("Story", encoding="utf-8")
    document_state.set_active_document(str(story))

    with patch.object(
        creative_tools.document_store,
        "search",
        return_value={"documents": [], "metadatas": []},
    ) as search:
        result = creative_tools.search_creative_document("secret")

    assert "No indexed passages" in result
    assert search.call_count == 1
