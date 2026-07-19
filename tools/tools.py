"""
Tool definitions for Jarvis.

Each tool has two parts:
  1. A JSON schema in TOOL_SCHEMAS, so the model knows the tool exists,
     what it does, and what arguments it takes.
  2. A Python function in TOOL_FUNCTIONS that actually runs it.

To add a new tool: write the function, add its schema to TOOL_SCHEMAS,
and register it in TOOL_FUNCTIONS. That's the whole contract -- brain/llm.py
doesn't need to change.
"""

import ast
import operator
from datetime import datetime
from pathlib import Path

from tools.file_manager import FILE_TOOL_SCHEMAS, FILE_TOOL_FUNCTIONS
from tools.system import SYSTEM_TOOL_SCHEMAS, SYSTEM_TOOL_FUNCTIONS, SYSTEM_RISKY_TOOLS
from tools.desktop_control import DESKTOP_TOOL_SCHEMAS, DESKTOP_TOOL_FUNCTIONS, DESKTOP_RISKY_TOOLS
from tools.web import WEB_TOOL_SCHEMAS, WEB_TOOL_FUNCTIONS
from tools.full_access_files import FULL_ACCESS_SCHEMAS, FULL_ACCESS_FUNCTIONS, FULL_ACCESS_RISKY_TOOLS
from tools.file_index import FILE_INDEX_SCHEMAS, FILE_INDEX_FUNCTIONS
from tools.git_tools import GIT_TOOL_SCHEMAS, GIT_TOOL_FUNCTIONS, GIT_RISKY_TOOLS
from tools.screen import SCREEN_TOOL_SCHEMAS, SCREEN_TOOL_FUNCTIONS, SCREEN_RISKY_TOOLS
from tools.memory_tools import MEMORY_TOOL_SCHEMAS, MEMORY_TOOL_FUNCTIONS
from tools.window_control import WINDOW_TOOL_SCHEMAS, WINDOW_TOOL_FUNCTIONS, WINDOW_RISKY_TOOLS


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_current_time() -> str:
    """Return the current local date and time."""
    return datetime.now().strftime("%A, %B %d, %Y %I:%M %p")


# Only these operators are permitted in calculate() -- this keeps it safe
# to evaluate model-provided expressions without using eval().
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _ALLOWED_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("Unsupported expression")


def calculate(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression, e.g. '12 * (3 + 4)'."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        return str(result)
    except Exception:
        return f"Could not evaluate '{expression}' as a math expression."


def list_directory(path: str = ".") -> str:
    """List the files and subfolders inside a directory."""
    try:
        target = Path(path).expanduser().resolve()
        entries = sorted(
            p.name + ("/" if p.is_dir() else "") for p in target.iterdir()
        )
        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:
        return f"Could not list '{path}': {e}"


# ---------------------------------------------------------------------------
# Schemas (Ollama / OpenAI-style function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current local date and time.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a basic arithmetic expression using "
                "+, -, *, /, %, and ** (power)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression to evaluate, e.g. '12 * (3 + 4)'.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and subfolders inside a directory on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list. Defaults to the current directory.",
                    },
                },
                "required": [],
            },
        },
    },
]

TOOL_SCHEMAS += FILE_TOOL_SCHEMAS
TOOL_SCHEMAS += SYSTEM_TOOL_SCHEMAS
TOOL_SCHEMAS += DESKTOP_TOOL_SCHEMAS
TOOL_SCHEMAS += WEB_TOOL_SCHEMAS
TOOL_SCHEMAS += FULL_ACCESS_SCHEMAS
TOOL_SCHEMAS += FILE_INDEX_SCHEMAS
TOOL_SCHEMAS += GIT_TOOL_SCHEMAS
TOOL_SCHEMAS += SCREEN_TOOL_SCHEMAS
TOOL_SCHEMAS += MEMORY_TOOL_SCHEMAS
TOOL_SCHEMAS += WINDOW_TOOL_SCHEMAS

TOOL_FUNCTIONS = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "list_directory": list_directory,
}
TOOL_FUNCTIONS.update(FILE_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(SYSTEM_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(DESKTOP_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(WEB_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(FULL_ACCESS_FUNCTIONS)
TOOL_FUNCTIONS.update(FILE_INDEX_FUNCTIONS)
TOOL_FUNCTIONS.update(GIT_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(SCREEN_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(MEMORY_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(WINDOW_TOOL_FUNCTIONS)

# Tools that change or affect something beyond Jarvis's own sandbox --
# brain/llm.py asks for confirmation before running any of these.
RISKY_TOOLS = set()
RISKY_TOOLS |= SYSTEM_RISKY_TOOLS
RISKY_TOOLS |= DESKTOP_RISKY_TOOLS
RISKY_TOOLS |= FULL_ACCESS_RISKY_TOOLS
RISKY_TOOLS |= GIT_RISKY_TOOLS
RISKY_TOOLS |= SCREEN_RISKY_TOOLS
RISKY_TOOLS |= WINDOW_RISKY_TOOLS
