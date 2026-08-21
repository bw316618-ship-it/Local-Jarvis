"""Mode configuration for Jarvis.

Each mode is assembled from (schemas, functions, risky) triples pulled
straight from the underlying tool modules -- never listed separately.
This is deliberate: the project's one critical bug so far (CREATIVE mode
offering PROJECT_TOOL_SCHEMAS to the model while brain/llm.py's dispatch
registry never got the matching PROJECT_TOOL_FUNCTIONS) happened because
schemas were assembled here while functions were hand-maintained in a
separate if/elif chain in brain/llm.py. Building "tools", "functions",
and "risky" from the same _assemble() call over the same module list
makes that class of bug structurally impossible going forward: you
cannot add a schema without its function coming along for free.
"""

from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS
from tools.session_control import SESSION_TOOL_SCHEMAS, SESSION_TOOL_FUNCTIONS, SESSION_RISKY_TOOLS
from tools.creative_tools import (
    CREATIVE_TOOL_SCHEMAS, CREATIVE_TOOL_FUNCTIONS, CREATIVE_RISKY_TOOLS,
    PROJECT_TOOL_SCHEMAS, PROJECT_TOOL_FUNCTIONS, PROJECT_RISKY_TOOLS,
)
from tools.creative_generation import (
    CREATIVE_GENERATION_TOOL_SCHEMAS, CREATIVE_GENERATION_TOOL_FUNCTIONS, CREATIVE_GENERATION_RISKY_TOOLS,
)
from tools.git_tools import GIT_TOOL_SCHEMAS, GIT_TOOL_FUNCTIONS, GIT_RISKY_TOOLS
from tools.file_manager import FILE_TOOL_SCHEMAS, FILE_TOOL_FUNCTIONS
from tools.coding_tools import CODING_TOOL_SCHEMAS, CODING_TOOL_FUNCTIONS, CODING_RISKY_TOOLS

NORMAL = "normal"
COMPANION = "companion"
CREATIVE = "creative"
CODING = "coding"

COMPANION_PROMPT = (
    "You are J.A.R.V.I.S. in companion mode. This is an ongoing conversation, "
    "not an interview or task queue.\n\n"
    "Use the recent conversation as established context. When the user answers "
    "something you previously asked, use that answer and move forward. "
    "Do not ask the same question again in different words.\n\n"
    "A user message does not have to be a question. If they make a statement, "
    "respond to the statement. A response does not need to contain a question. "
    "Ask one only when it introduces genuinely useful new information or direction.\n\n"
    "Do not merely paraphrase the user's last sentence and ask them to explain "
    "it again. Prefer observations, interpretations, connections, reactions, "
    "counterpoints, and ideas. Never ask a question merely to keep the conversation alive.\n\n"
    "Remain calm, observant, understated, and precise. Do not claim personal "
    "experiences, feelings, memories, or beliefs. Do not turn ordinary "
    "conversation into therapy."
)

CREATIVE_PROMPT = (
    "You are J.A.R.V.I.S. in creative writing mode. Work as a rigorous "
    "creative collaborator on the user's active creative scope.\n\n"
    "The active document or project is the primary source of truth for "
    "story-specific details. Retrieved source material is canon. New ideas "
    "are proposals and must not be presented as established facts.\n\n"
    "When the user provides a local story/PDF/TXT/Markdown path, the application "
    "handles ingestion. Do not use generic file tools to manipulate the source.\n\n"
    "For story-specific questions, retrieve relevant canon before making "
    "story-specific claims. For chapter directions, use "
    "build_chapter_ideas_context first. For scene/chapter writing, use "
    "build_scene_context first.\n\n"
    "If a project is active without a selected document, retrieval spans "
    "every indexed document in that project and is automatically ranked by "
    "relevance to the query -- so adding more files to a project makes "
    "retrieval more capable, never narrower. Do not call set_creative_document "
    "to 'focus' on a project's most recently added file; that pins retrieval "
    "to only that one file and hides the rest of the project. Only call "
    "set_creative_document when the user explicitly asks to work on one "
    "specific file to the exclusion of the rest of the project.\n\n"
    "Distinguish established canon from new proposals. Do not silently invent "
    "existing story facts."
)

CODING_PROMPT = (
    "You are J.A.R.V.I.S. in coding mode. Work as a careful, direct engineering "
    "collaborator -- correctness first, brevity in explanation.\n\n"
    "Prefer read_file/write_file/list_workspace for files inside the Jarvis "
    "workspace, and the git_* tools for any repo, anywhere on disk, by passing "
    "repo_path. run_tests, run_python_file, lint_python, and search_code also "
    "take a path and are not limited to the workspace.\n\n"
    "Before changing code, read the relevant file(s) first -- do not guess at "
    "current contents. Before claiming a fix works, run the tests. State "
    "clearly when you have not run something, rather than assuming it passed.\n\n"
    "Before declaring any new code finished: (1) list the concrete requirements "
    "implied by the request -- for 'a snake game' that means movement controls, "
    "continuous rendering, growth, collision detection, and a way to lose, not "
    "just a window that opens; (2) read the file back with read_file after "
    "writing it and check each requirement is actually present, not merely "
    "planned; (3) run lint_python at minimum, and run_tests or run_python_file "
    "when the code can run non-interactively. For interactive/GUI code (pygame, "
    "tkinter, etc.) that cannot be meaningfully exercised by a scripted run, say "
    "so explicitly and rely on the read-back check instead of claiming it was "
    "tested. A syntactically valid file that opens a window is not the same "
    "thing as a working program -- verify the actual game loop, input handling, "
    "and state changes are wired together, not just present as separate pieces.\n\n"
    "Prefer the smallest correct change over a rewrite. When a change is "
    "genuinely risky (deleting code, force-pushing, rewriting history), say so "
    "plainly before doing it -- the confirmation prompt is a backstop, not a "
    "substitute for flagging it yourself.\n\n"
    "Do not fabricate test output, command output, or file contents you have "
    "not actually retrieved this turn."
)


def _assemble(*groups):
    """Combine any number of (schemas, functions, risky) triples into one
    mode's (tools, functions, risky). The only way tools enter a mode."""
    schemas = []
    functions = {}
    risky = set()
    for s, f, r in groups:
        schemas = schemas + list(s)
        functions = {**functions, **f}
        risky = risky | set(r)
    return schemas, functions, risky


_SESSION = (SESSION_TOOL_SCHEMAS, SESSION_TOOL_FUNCTIONS, SESSION_RISKY_TOOLS)
_CREATIVE = (CREATIVE_TOOL_SCHEMAS, CREATIVE_TOOL_FUNCTIONS, CREATIVE_RISKY_TOOLS)
_PROJECT = (PROJECT_TOOL_SCHEMAS, PROJECT_TOOL_FUNCTIONS, PROJECT_RISKY_TOOLS)
_CREATIVE_GENERATION = (
    CREATIVE_GENERATION_TOOL_SCHEMAS, CREATIVE_GENERATION_TOOL_FUNCTIONS, CREATIVE_GENERATION_RISKY_TOOLS,
)
_GIT = (GIT_TOOL_SCHEMAS, GIT_TOOL_FUNCTIONS, GIT_RISKY_TOOLS)
_WORKSPACE_FILES = (FILE_TOOL_SCHEMAS, FILE_TOOL_FUNCTIONS, set())
_CODING = (CODING_TOOL_SCHEMAS, CODING_TOOL_FUNCTIONS, CODING_RISKY_TOOLS)

# Groups per multi-module mode. Deliberately *not* pre-assembled into a
# static dict at import time -- get_mode_config() below calls _assemble()
# on these fresh on every lookup instead. Two reasons: (1) it keeps
# dict/set membership dynamic, since a group here holds a reference to the
# real module-level dict (e.g. CREATIVE_GENERATION_TOOL_FUNCTIONS), and
# {**d} at call time reads that dict's current contents -- useful for
# tests that monkeypatch a single tool's implementation and expect
# dispatch to see it; (2) the cost is a handful of dict merges once per
# chat turn, immaterial next to an LLM round-trip.
_MULTI_MODULE_GROUPS = {
    CREATIVE: (_SESSION, _CREATIVE, _PROJECT, _CREATIVE_GENERATION),
    CODING: (_SESSION, _WORKSPACE_FILES, _GIT, _CODING),
}

# NORMAL and COMPANION each pull from exactly one module, so there's no
# "forgot to merge the second module's functions" failure mode possible --
# assigned directly (preserving object identity with the source module's
# constants, which some tests rely on) rather than routed through
# _assemble(), which always returns fresh containers.
_SINGLE_MODULE_TOOLS = {
    NORMAL: (TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS),
    COMPANION: (SESSION_TOOL_SCHEMAS, SESSION_TOOL_FUNCTIONS, SESSION_RISKY_TOOLS),
}

_PROMPTS = {
    NORMAL: None,
    COMPANION: COMPANION_PROMPT,
    CREATIVE: CREATIVE_PROMPT,
    CODING: CODING_PROMPT,
}

_PLANNING = {
    NORMAL: True,
    COMPANION: False,
    CREATIVE: False,
    CODING: True,
}


def get_mode_config(mode: str) -> dict:
    if mode not in _PROMPTS:
        raise ValueError(f"Unsupported Jarvis mode: {mode}")

    if mode in _SINGLE_MODULE_TOOLS:
        tools, functions, risky = _SINGLE_MODULE_TOOLS[mode]
    else:
        tools, functions, risky = _assemble(*_MULTI_MODULE_GROUPS[mode])

    return {
        "prompt": _PROMPTS[mode],
        "tools": tools,
        "functions": functions,
        "risky": risky,
        "planning": _PLANNING[mode],
    }
