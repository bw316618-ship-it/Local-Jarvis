"""Guards against creative mode's overlapping retrieval tools (get_creative_
context / build_chapter_ideas_context / build_scene_context /
search_creative_document / search_creative_project) drifting back into
ambiguous, near-identical descriptions.

These five tools were kept (not removed) despite real overlap in what
they can end up doing -- search_creative_document has genuine, tested
functional coverage across several other test files, and removing it
would mean rewriting working tests to solve a smaller problem than that
would cost. The actual fix was sharpening each tool's stated purpose so
a model reads them as distinct choices rather than near-duplicates. This
file exists so that distinction can't silently erode back to vague
one-liners in a later edit without a test noticing.
"""

from tools.creative_generation import CREATIVE_GENERATION_TOOL_SCHEMAS
from tools.creative_tools import CREATIVE_TOOL_SCHEMAS, PROJECT_TOOL_SCHEMAS


def _description(schemas, name):
    for s in schemas:
        if s["function"]["name"] == name:
            return s["function"]["description"]
    raise AssertionError(f"{name} not found in schema list")


def test_all_five_retrieval_tools_still_present():
    creative_names = {s["function"]["name"] for s in CREATIVE_TOOL_SCHEMAS}
    project_names = {s["function"]["name"] for s in PROJECT_TOOL_SCHEMAS}
    generation_names = {s["function"]["name"] for s in CREATIVE_GENERATION_TOOL_SCHEMAS}

    assert "search_creative_document" in creative_names
    assert "search_creative_project" in project_names
    assert {"get_creative_context", "build_chapter_ideas_context", "build_scene_context"} <= generation_names


def test_no_two_retrieval_tool_descriptions_are_identical():
    descriptions = [
        _description(CREATIVE_TOOL_SCHEMAS, "search_creative_document"),
        _description(PROJECT_TOOL_SCHEMAS, "search_creative_project"),
        _description(CREATIVE_GENERATION_TOOL_SCHEMAS, "get_creative_context"),
        _description(CREATIVE_GENERATION_TOOL_SCHEMAS, "build_chapter_ideas_context"),
        _description(CREATIVE_GENERATION_TOOL_SCHEMAS, "build_scene_context"),
    ]
    assert len(set(descriptions)) == len(descriptions)


def test_get_creative_context_is_framed_as_the_default_choice():
    description = _description(CREATIVE_GENERATION_TOOL_SCHEMAS, "get_creative_context").lower()
    assert "default" in description


def test_search_creative_document_states_it_bypasses_project_scope():
    description = _description(CREATIVE_TOOL_SCHEMAS, "search_creative_document").lower()
    assert "only" in description or "ignoring" in description
    # Should also point the model back toward the default tool.
    assert "get_creative_context" in description


def test_search_creative_project_states_it_covers_the_whole_project():
    description = _description(PROJECT_TOOL_SCHEMAS, "search_creative_project").lower()
    assert "every document" in description or "whole project" in description
    assert "get_creative_context" in description
