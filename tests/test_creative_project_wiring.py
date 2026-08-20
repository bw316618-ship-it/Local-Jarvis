"""Regression tests for the project-tool dispatch bug.

brain/mode_config.py's CREATIVE tool list included PROJECT_TOOL_SCHEMAS (so
the model was told set_creative_project/list_creative_projects/etc. exist
and can be called), but brain/llm.py's _tool_registry_for_mode() never
merged in PROJECT_TOOL_FUNCTIONS -- so every one of those calls resolved to
"Error: unknown tool" no matter what the model did. test_creative_generation_wiring.py
already covered this exact pattern for the generation tools and passed,
which is exactly why this went unnoticed: the project tools needed the
same test and never got it.
"""

from unittest.mock import MagicMock

import pytest

from brain.llm import JarvisLLM
from brain.mode_config import COMPANION, CODING, CREATIVE, NORMAL, get_mode_config
from tools.creative_tools import PROJECT_TOOL_FUNCTIONS
from voice import document_state, session_state


def setup_function():
    session_state.set_mode(NORMAL)
    document_state.clear_scope()


def teardown_function():
    session_state.set_mode(NORMAL)
    document_state.clear_scope()


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK"
    jarvis.companion_system_prompt = "COMPANION"
    jarvis.model = "qwen3:8b"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


# --- the general regression guard: every schema name offered to the model
# in a mode must resolve to a real callable in that mode's registry. This
# is the test that should have existed before the project tools shipped,
# and should catch the *next* tool added to a schema list and forgotten in
# the registry, regardless of which tool it is. ---------------------------

@pytest.mark.parametrize("mode", [NORMAL, COMPANION, CREATIVE, CODING])
def test_every_offered_schema_resolves_in_that_modes_registry(mode):
    jarvis = make_jarvis()
    session_state.set_mode(mode)

    offered_names = {
        item["function"]["name"] for item in get_mode_config(mode)["tools"]
    }
    registry, _ = jarvis._tool_registry_for_mode(mode)

    missing = offered_names - set(registry)
    assert not missing, (
        f"Tool(s) offered to the model in {mode!r} mode but not resolvable "
        f"in the dispatch registry: {missing}"
    )


# --- the specific bug -----------------------------------------------------

def test_project_tools_resolve_in_creative_registry():
    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    registry, risky = jarvis._tool_registry_for_mode(CREATIVE)

    for name in PROJECT_TOOL_FUNCTIONS:
        assert name in registry, f"{name} missing from CREATIVE registry"
    assert "set_creative_project" not in risky


def test_set_creative_project_callable_through_run_tool_call(monkeypatch, tmp_path):
    import memory.project_memory as project_memory
    monkeypatch.setattr(project_memory, "PROJECTS_PATH", tmp_path / "creative_projects.json")

    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    result = jarvis._run_tool_call(
        {
            "function": {
                "name": "set_creative_project",
                "arguments": {"name": "The Crownbreaker"},
            }
        }
    )

    assert "unknown tool" not in result.lower()
    assert "Crownbreaker" in result
    assert document_state.get_active_project() == "The Crownbreaker"


def test_list_and_get_creative_project_callable_through_run_tool_call(monkeypatch, tmp_path):
    import memory.project_memory as project_memory
    monkeypatch.setattr(project_memory, "PROJECTS_PATH", tmp_path / "creative_projects.json")

    jarvis = make_jarvis()
    session_state.set_mode(CREATIVE)

    jarvis._run_tool_call(
        {"function": {"name": "set_creative_project", "arguments": {"name": "Novel A"}}}
    )
    listed = jarvis._run_tool_call(
        {"function": {"name": "list_creative_projects", "arguments": {}}}
    )
    got = jarvis._run_tool_call(
        {"function": {"name": "get_creative_project", "arguments": {}}}
    )

    assert "unknown tool" not in listed.lower()
    assert "Novel A" in listed
    assert "unknown tool" not in got.lower()
    assert "Novel A" in got


def test_add_document_creates_project_if_needed_and_dedupes(tmp_path, monkeypatch):
    """Covers memory/project_memory.py's add_document -- previously untested,
    which is how the redundant double load/save went unnoticed. Verifies
    the collapsed single-load version still creates a new project on first
    use and doesn't duplicate an already-registered document path.

    Uses Path(...).resolve() to build the expected value rather than a
    hardcoded POSIX literal, since add_document resolves the path itself
    and that resolution is platform-dependent (e.g. /tmp/chapter1.txt
    resolves to C:\\tmp\\chapter1.txt on Windows)."""
    import memory.project_memory as project_memory
    from pathlib import Path
    monkeypatch.setattr(project_memory, "PROJECTS_PATH", tmp_path / "creative_projects.json")

    chapter1 = str(Path("chapter1.txt").resolve())
    chapter2 = str(Path("chapter2.txt").resolve())

    record = project_memory.add_document("Fresh Project", chapter1)
    assert record["name"] == "Fresh Project"
    assert chapter1 in record["documents"]

    record = project_memory.add_document("Fresh Project", chapter1)
    assert record["documents"].count(chapter1) == 1

    record = project_memory.add_document("Fresh Project", chapter2)
    assert len(record["documents"]) == 2


def test_project_tools_not_present_in_normal_or_companion_registry():
    jarvis = make_jarvis()

    session_state.set_mode(NORMAL)
    registry, _ = jarvis._tool_registry_for_mode(NORMAL)
    assert "set_creative_project" not in registry

    session_state.set_mode(COMPANION)
    registry, _ = jarvis._tool_registry_for_mode(COMPANION)
    assert "set_creative_project" not in registry
