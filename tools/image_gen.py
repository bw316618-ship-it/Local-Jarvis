"""
Local image generation for Jarvis, via an AUTOMATIC1111 Stable Diffusion
WebUI instance running on the same machine (its `--api` flag exposes a
plain HTTP/JSON API on http://127.0.0.1:7860 by default).

AUTOMATIC1111, not a cloud image API: the whole point of Local-Jarvis is
that nothing leaves the machine. AUTOMATIC1111's REST API is the
simplest local option that fits the existing "talk to a local HTTP
server" shape already used for Ollama -- ComfyUI's graph-based API would
work too, but needs a workflow-JSON per request rather than a flat
prompt, which doesn't fit a single simple tool call.

This does NOT bundle or install Stable Diffusion, any checkpoint, or
AUTOMATIC1111 itself -- same stance as Ollama models and Piper voices
elsewhere in this project: a real diffusion model needs real GPU VRAM
(several GB, on top of whatever the chat LLM is already holding), which
cannot be assumed for every machine Jarvis runs on. If AUTOMATIC1111
isn't reachable at `automatic1111_url`, this fails with a clear,
actionable message rather than a stack trace -- the same "degrades
gracefully" pattern as tools/routing.py's keyless OSRM fallback and
tools/location.py's GeoLite2 fallback, except there is no fallback for
local image generation itself: either a local diffusion server is
running, or it isn't.

Registered as risky: it writes an image file to disk and can tie up the
GPU/CPU for tens of seconds.
"""

import base64
import binascii

import requests

from config import CONFIG

DEFAULT_URL = "http://127.0.0.1:7860"
# Generation itself can legitimately take 30s-several minutes on modest
# hardware -- deliberately NOT using tools/net.py's retry wrapper here,
# since retrying a slow request that's still genuinely in progress would
# just double (or triple) the wait rather than recover from anything.
GENERATION_TIMEOUT_SECONDS = 180


def _base_url() -> str:
    return (CONFIG.get("automatic1111_url") or DEFAULT_URL).rstrip("/")


def generate_image(
    prompt: str,
    negative_prompt: str = "",
    save_path: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
) -> str:
    """Generate an image from a text prompt using a local AUTOMATIC1111
    Stable Diffusion server and save it as a PNG."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "A prompt is required."

    width = max(64, min(int(width), 1536))
    height = max(64, min(int(height), 1536))
    steps = max(1, min(int(steps), 150))

    url = f"{_base_url()}/sdapi/v1/txt2img"
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "width": width,
        "height": height,
        "steps": steps,
    }

    try:
        response = requests.post(url, json=payload, timeout=GENERATION_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return (
            "Local image generation isn't available: no AUTOMATIC1111 "
            f"server found at {_base_url()}. Start it with the `--api` "
            "flag, or point 'automatic1111_url' in jarvis_config.json at "
            "wherever it's running."
        )
    except requests.exceptions.Timeout:
        return (
            f"Image generation timed out after {GENERATION_TIMEOUT_SECONDS}s. "
            "Try fewer steps or a smaller width/height on modest hardware."
        )
    except requests.exceptions.HTTPError as e:
        return f"AUTOMATIC1111 rejected the request: {e}"
    except requests.RequestException as e:
        return f"Could not reach the local image generation server: {e}"

    try:
        data = response.json()
        images = data.get("images") or []
        if not images:
            return "The image generation server returned no image."
        image_bytes = base64.b64decode(images[0])
    except (ValueError, binascii.Error) as e:
        return f"Could not decode the generated image: {e}"

    from pathlib import Path
    import tempfile

    target = (
        Path(save_path).expanduser()
        if save_path
        else Path(tempfile.gettempdir()) / "jarvis_generated.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image_bytes)

    return f"Generated image saved to '{target}'."


IMAGE_GEN_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image from a text prompt using a local "
                "Stable Diffusion server (AUTOMATIC1111) and save it as a "
                "PNG. Requires AUTOMATIC1111 to already be running locally "
                "with its API enabled -- fails with a clear message if it "
                "isn't. This can take anywhere from tens of seconds to "
                "several minutes depending on hardware, and writes a file, "
                "so it requires confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What to generate, as a text description.",
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "What to avoid in the generated image.",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Where to save the generated image. Defaults to a temp file if omitted.",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Image width in pixels (default 512).",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Image height in pixels (default 512).",
                    },
                    "steps": {
                        "type": "integer",
                        "description": "Diffusion sampling steps -- higher is slower but often cleaner (default 20).",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]

IMAGE_GEN_TOOL_FUNCTIONS = {
    "generate_image": generate_image,
}

IMAGE_GEN_RISKY_TOOLS = {"generate_image"}
