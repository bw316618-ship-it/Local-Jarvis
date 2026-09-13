from unittest.mock import patch

from memory import conversation_memory, project_memory
from voice import document_state


def setup_function():
    document_state.clear_scope()


def teardown_function():
    document_state.clear_scope()


def test_creative_project_blocks_global_conversation_recall():
    document_state.set_active_project("Faint")

    with patch.object(
        conversation_memory,
        "_get_collection",
    ) as get_collection:
        result = conversation_memory.recall("what project are we on?")

    assert result == []
    get_collection.assert_not_called()


def test_creative_project_blocks_global_fact_recall():
    document_state.set_active_project("Faint")

    with patch.object(
        conversation_memory,
        "_get_facts_collection",
    ) as get_collection:
        result = conversation_memory.recall_facts("what project are we on?")

    assert result == []
    get_collection.assert_not_called()


def test_creative_project_turn_is_not_saved_to_global_memory():
    document_state.set_active_project("Faint")

    with patch.object(
        conversation_memory,
        "_get_collection",
    ) as get_collection:
        conversation_memory.remember_turn(
            "What project are we on?",
            "Faint",
        )

    get_collection.assert_not_called()


def test_project_registry_remains_authoritative(tmp_path, monkeypatch):
    monkeypatch.setattr(
        project_memory,
        "PROJECTS_PATH",
        tmp_path / "creative_projects.json",
    )

    project_memory.ensure_project("Faint")

    document = tmp_path / "The.pdf"
    document.write_bytes(b"x")

    project_memory.add_document("Faint", str(document))
    document_state.set_active_project("Faint")

    assert project_memory.get_document_paths("Faint") == [
        str(document.resolve())
    ]
