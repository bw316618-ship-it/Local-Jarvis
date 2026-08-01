"""
Vision for Jarvis, via Ollama's moondream model.

Complements tools/screen.py: read_screen_text (OCR) only ever sees text
that's literally rendered on screen -- it can't tell you a photo shows a
sunset, that an icon is a trash can, or what's in a picture with no text
at all. describe_image asks a small local vision-language model instead,
so Jarvis can answer "what's on my screen" or "what's in this photo" for
genuinely visual content, not just transcribed text.

Requires the moondream model to be pulled locally (`ollama pull
moondream`) -- not part of requirements.txt since it's a model download,
not a Python package. Everything still runs fully offline through the
same local Ollama server every other tool already talks to.

Read-only (looking at an image never changes anything), so this isn't
registered as risky.
"""

import tempfile
from pathlib import Path

from ollama import Client

VISION_MODEL = "moondream"
DEFAULT_QUESTION = "Describe what you see in this image, in a couple of sentences."


def _get_client():
    return Client(host="http://localhost:11434")


def describe_image(path: str = "", question: str = "") -> str:
    """Describe an image, or answer a question about it.

    If `path` is omitted, captures the current screen first (reusing
    tools/screen.py's screenshot capture) and describes that instead --
    this is the "what's on my screen" case, distinct from
    read_screen_text which only reads text, not layout/icons/images.
    """
    question = (question or "").strip() or DEFAULT_QUESTION

    tmp_path = None
    if path:
        image_path = Path(path).expanduser().resolve()
        if not image_path.exists():
            return f"'{path}' does not exist."
        if image_path.is_dir():
            return f"'{path}' is a directory, not an image file."
    else:
        try:
            from tools.screen import _take_screenshot
            image = _take_screenshot()
        except RuntimeError as e:
            return str(e)
        except Exception as e:
            return f"Could not capture the screen: {e}"

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        image.save(tmp_path)
        image_path = Path(tmp_path)

    try:
        client = _get_client()
        response = client.chat(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": question,
                    "images": [str(image_path)],
                }
            ],
        )
        return response["message"]["content"].strip()
    except Exception as e:
        return (
            f"Vision isn't available: {e}. Make sure Ollama is running and "
            f"the vision model is pulled: ollama pull {VISION_MODEL}"
        )
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


VISION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "describe_image",
            "description": (
                "Describe an image file, or (if no path is given) the current "
                "screen, and optionally answer a specific question about it. "
                "Unlike read_screen_text, which only reads visible TEXT, this "
                "understands actual visual content -- photos, icons, layout, "
                "diagrams, colors, objects. Use this for 'what's in this "
                "picture' or 'what does my screen look like right now' rather "
                "than 'what does it say'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to an image file. Omit to capture and describe the current screen instead.",
                    },
                    "question": {
                        "type": "string",
                        "description": "A specific question to ask about the image, e.g. 'is there a red car here?'. Defaults to a general description.",
                    },
                },
                "required": [],
            },
        },
    },
]

VISION_TOOL_FUNCTIONS = {
    "describe_image": describe_image,
}

# Read-only -- looking at an image never changes anything.
VISION_RISKY_TOOLS = set()
