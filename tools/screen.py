"""
Screen understanding for Jarvis: screenshots + OCR.

Reuses pyautogui (already a dependency for mouse/keyboard control) to
capture the screen, and rapidocr-onnxruntime to extract text from it --
fully local, no external OCR binary like Tesseract required.

read_screen_text and find_text_on_screen are read-only (they only look
at the screen, never change anything) and aren't registered as risky.
take_screenshot is different: it writes a PNG to a path the caller
supplies, creating any missing parent directories along the way. An
arbitrary-path file write is exactly the kind of action every other
write tool in this codebase (write_file, write_any_file, ...) requires
confirmation for, so this one is registered as risky too rather than
being lumped in with the two genuinely read-only tools above it.

Worth knowing: this only reads TEXT on screen, not icons, images, or
layout -- for actual visual understanding of arbitrary UI (icons,
photos, layout), use describe_image in tools/vision.py instead, which
asks a local vision-language model (moondream) rather than OCR-ing text.
"""

import tempfile
from pathlib import Path

_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "OCR isn't available: rapidocr-onnxruntime couldn't load. "
                "Run: pip install -r requirements.txt"
            ) from e
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _take_screenshot():
    try:
        import pyautogui
    except (ImportError, OSError) as e:
        raise RuntimeError(
            "Screenshots aren't available: pyautogui couldn't load or "
            "there's no display to capture. Run: pip install -r requirements.txt"
        ) from e

    try:
        return pyautogui.screenshot()
    except Exception as e:
        raise RuntimeError(f"Could not capture the screen: {e}") from e


def take_screenshot(save_path: str = "") -> str:
    """Capture the current screen and save it as a PNG."""
    try:
        image = _take_screenshot()
    except RuntimeError as e:
        return str(e)

    target = Path(save_path).expanduser() if save_path else Path(tempfile.gettempdir()) / "jarvis_screenshot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(target))
    return f"Screenshot saved to '{target}' ({image.width}x{image.height})."


def read_screen_text() -> str:
    """Capture the screen and OCR it, returning all visible text."""
    try:
        image = _take_screenshot()
        engine = _get_ocr_engine()
    except RuntimeError as e:
        return str(e)

    import numpy as np
    result, _ = engine(np.array(image))

    if not result:
        return "No text detected on screen."

    lines = [entry[1] for entry in result]
    return "Text visible on screen:\n" + "\n".join(lines)


def find_text_on_screen(query: str) -> str:
    """Find where a piece of text appears on screen, returning matches and click coordinates."""
    try:
        image = _take_screenshot()
        engine = _get_ocr_engine()
    except RuntimeError as e:
        return str(e)

    import numpy as np
    result, _ = engine(np.array(image))

    if not result:
        return f"No text detected on screen (looking for '{query}')."

    query_lower = query.lower()
    matches = []
    for bbox, text, confidence in result:
        if query_lower in text.lower():
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            center_x = int(sum(xs) / len(xs))
            center_y = int(sum(ys) / len(ys))
            matches.append((text, center_x, center_y))

    if not matches:
        return f"No text matching '{query}' found on screen."

    lines = [f'- "{text}" at ({x}, {y})' for text, x, y in matches]
    return "Matches found (use mouse_click with these coordinates to click one):\n" + "\n".join(lines)


SCREEN_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": (
                "Capture a screenshot of the current screen and save it as a PNG "
                "file. If you just need to know what's currently on screen rather "
                "than save a file, use describe_image or read_screen_text instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "save_path": {
                        "type": "string",
                        "description": "Where to save the screenshot. Defaults to a temp file if omitted.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_screen_text",
            "description": "Capture the screen and read all visible text on it via OCR. Use this to know what's currently displayed.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_text_on_screen",
            "description": (
                "Find where specific text (e.g. a button label) appears on "
                "screen right now, returning its screen coordinates. Use this "
                "before mouse_click when you need to click something by its "
                "visible label rather than a coordinate you already know."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The text to search for on screen, e.g. 'Save' or 'Submit'."},
                },
                "required": ["query"],
            },
        },
    },
]

SCREEN_TOOL_FUNCTIONS = {
    "take_screenshot": take_screenshot,
    "read_screen_text": read_screen_text,
    "find_text_on_screen": find_text_on_screen,
}

# take_screenshot writes an arbitrary file to disk, so it's risky like any
# other write tool. read_screen_text/find_text_on_screen only look at the
# screen and never change anything.
SCREEN_RISKY_TOOLS = {"take_screenshot"}
