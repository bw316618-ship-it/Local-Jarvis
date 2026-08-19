"""
Tool definitions for Jarvis.

The normal task registry remains the full tool set. Specialized modes
declare their own subsets through their mode configuration.
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
from tools.memory_tools import MEMORY_TOOL_SCHEMAS, MEMORY_TOOL_FUNCTIONS, MEMORY_RISKY_TOOLS
from tools.window_control import WINDOW_TOOL_SCHEMAS, WINDOW_TOOL_FUNCTIONS, WINDOW_RISKY_TOOLS
from tools.diagnostics import DIAGNOSTICS_TOOL_SCHEMAS, DIAGNOSTICS_TOOL_FUNCTIONS, DIAGNOSTICS_RISKY_TOOLS
from tools.vision import VISION_TOOL_SCHEMAS, VISION_TOOL_FUNCTIONS, VISION_RISKY_TOOLS
from tools.location import LOCATION_TOOL_SCHEMAS, LOCATION_TOOL_FUNCTIONS, LOCATION_RISKY_TOOLS
from tools.calendar_tool import CALENDAR_TOOL_SCHEMAS, CALENDAR_TOOL_FUNCTIONS, CALENDAR_RISKY_TOOLS
from tools.pdf_viewer import PDF_TOOL_SCHEMAS, PDF_TOOL_FUNCTIONS, PDF_RISKY_TOOLS
from tools.datasheet import DATASHEET_TOOL_SCHEMAS, DATASHEET_TOOL_FUNCTIONS, DATASHEET_RISKY_TOOLS
from tools.media import MEDIA_TOOL_SCHEMAS, MEDIA_TOOL_FUNCTIONS, MEDIA_RISKY_TOOLS
from tools.session_control import SESSION_TOOL_SCHEMAS, SESSION_TOOL_FUNCTIONS, SESSION_RISKY_TOOLS
from tools.nearby import NEARBY_TOOL_SCHEMAS, NEARBY_TOOL_FUNCTIONS, NEARBY_RISKY_TOOLS
from tools.routing import ROUTING_TOOL_SCHEMAS, ROUTING_TOOL_FUNCTIONS, ROUTING_RISKY_TOOLS
from tools.maps import MAPS_TOOL_SCHEMAS, MAPS_TOOL_FUNCTIONS, MAPS_RISKY_TOOLS
from tools.weather import WEATHER_TOOL_SCHEMAS, WEATHER_TOOL_FUNCTIONS, WEATHER_RISKY_TOOLS
from tools.creative_tools import (
    CREATIVE_TOOL_SCHEMAS,
    CREATIVE_TOOL_FUNCTIONS,
    CREATIVE_RISKY_TOOLS,
)


def get_current_time() -> str:
    return datetime.now().strftime("%A, %B %d, %Y %I:%M %p")


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
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        return str(result)
    except Exception:
        return f"Could not evaluate '{expression}' as a math expression."


def list_directory(path: str = ".") -> str:
    try:
        target = Path(path).expanduser().resolve()
        entries = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in target.iterdir()
        )
        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:
        return f"Could not list '{path}': {e}"


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
            "description": "Evaluate a basic arithmetic expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression to evaluate.",
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
            "description": "List files and subfolders inside a known directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path.",
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
TOOL_SCHEMAS += DIAGNOSTICS_TOOL_SCHEMAS
TOOL_SCHEMAS += VISION_TOOL_SCHEMAS
TOOL_SCHEMAS += LOCATION_TOOL_SCHEMAS
TOOL_SCHEMAS += CALENDAR_TOOL_SCHEMAS
TOOL_SCHEMAS += PDF_TOOL_SCHEMAS
TOOL_SCHEMAS += DATASHEET_TOOL_SCHEMAS
TOOL_SCHEMAS += MEDIA_TOOL_SCHEMAS
TOOL_SCHEMAS += SESSION_TOOL_SCHEMAS
TOOL_SCHEMAS += NEARBY_TOOL_SCHEMAS
TOOL_SCHEMAS += ROUTING_TOOL_SCHEMAS
TOOL_SCHEMAS += MAPS_TOOL_SCHEMAS
TOOL_SCHEMAS += WEATHER_TOOL_SCHEMAS

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
TOOL_FUNCTIONS.update(DIAGNOSTICS_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(VISION_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(LOCATION_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(CALENDAR_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(PDF_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(DATASHEET_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(MEDIA_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(SESSION_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(NEARBY_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(ROUTING_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(MAPS_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(WEATHER_TOOL_FUNCTIONS)
TOOL_FUNCTIONS.update(CREATIVE_TOOL_FUNCTIONS)

RISKY_TOOLS = set()
RISKY_TOOLS |= SYSTEM_RISKY_TOOLS
RISKY_TOOLS |= DESKTOP_RISKY_TOOLS
RISKY_TOOLS |= FULL_ACCESS_RISKY_TOOLS
RISKY_TOOLS |= GIT_RISKY_TOOLS
RISKY_TOOLS |= SCREEN_RISKY_TOOLS
RISKY_TOOLS |= MEMORY_RISKY_TOOLS
RISKY_TOOLS |= WINDOW_RISKY_TOOLS
RISKY_TOOLS |= DIAGNOSTICS_RISKY_TOOLS
RISKY_TOOLS |= VISION_RISKY_TOOLS
RISKY_TOOLS |= LOCATION_RISKY_TOOLS
RISKY_TOOLS |= CALENDAR_RISKY_TOOLS
RISKY_TOOLS |= PDF_RISKY_TOOLS
RISKY_TOOLS |= DATASHEET_RISKY_TOOLS
RISKY_TOOLS |= MEDIA_RISKY_TOOLS
RISKY_TOOLS |= SESSION_RISKY_TOOLS
RISKY_TOOLS |= NEARBY_RISKY_TOOLS
RISKY_TOOLS |= ROUTING_RISKY_TOOLS
RISKY_TOOLS |= MAPS_RISKY_TOOLS
RISKY_TOOLS |= WEATHER_RISKY_TOOLS
RISKY_TOOLS |= CREATIVE_RISKY_TOOLS
