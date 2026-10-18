"""
Webcam capture for Jarvis, plus an optional "X-ray vision" stylized
effect on top of it.

Complements tools/vision.py and tools/screen.py: those cover what's on
screen or in a saved image file, but neither can see the physical room
Jarvis is sitting in. capture_webcam_image and describe_webcam grab a
single frame from the default camera via OpenCV (cv2.VideoCapture) --
no continuous recording or streaming, one still frame per call, camera
released immediately after.

Requires opencv-python (cv2) -- not part of requirements.txt, since
pulling in OpenCV unconditionally for every Jarvis install (voice-only,
headless daemon, etc.) is a heavy, often-unused dependency. Degrades
gracefully with a clear install message if it isn't present, same
pattern as tools/screen.py's rapidocr-onnxruntime check.

X-ray effect: this is a *visual stylization*, not real X-ray/thermal
imaging -- there is no hardware here capable of that. It inverts the
frame, converts to grayscale, pulls out edges, and tints the result
cyan/blue, the same sci-fi "see-through" look used in plenty of camera
filter apps. describe_webcam can run the vision model against either
the plain or the stylized frame, so "what does the X-ray see" gets an
honest answer about the filtered image, not a claim about seeing
through anything.

Risk classification: capture_webcam_image is risky for the same reason
tools/screen.py's take_screenshot is -- it writes an arbitrary file to
disk. describe_webcam doesn't write a file (temp frame is deleted right
after, mirroring describe_image's own screen-capture branch), but it's
still marked risky here, unlike describe_image: turning on a physical
camera captures whatever is actually in front of it (people, the room),
a materially different privacy boundary than reading a screen the user
already has displayed. Both tools only ever grab a single frame and
release the camera immediately -- no background/continuous capture.
"""

import tempfile
from pathlib import Path

from ollama import Client

from tools.vision import VISION_MODEL, DEFAULT_QUESTION


def _open_camera():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError(
            "Webcam capture isn't available: opencv-python isn't installed. "
            "Run: pip install opencv-python"
        ) from e

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            "Could not open the webcam -- no camera found, it's in use by "
            "another application, or permission was denied."
        )
    return cv2, camera


def _capture_frame():
    """Grab one frame from the default camera. Opens and releases the
    camera for this single call only -- never left running in the
    background."""
    cv2, camera = _open_camera()
    try:
        # Many webcams return a dark/stale first frame while auto-exposure
        # settles; a couple of warm-up reads before the one we keep is a
        # common, cheap fix.
        for _ in range(2):
            camera.read()
        ok, frame = camera.read()
        if not ok or frame is None:
            raise RuntimeError("The webcam did not return a frame.")
        return cv2, frame
    finally:
        camera.release()


def _apply_xray_effect(cv2, frame):
    """Stylized 'X-ray vision' look: grayscale -> edges -> invert ->
    cyan/blue tint. Purely cosmetic image processing, not real X-ray or
    thermal imaging."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    inverted = cv2.bitwise_not(edges)

    tinted = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
    # Suppress red, keep green/blue strong -- a cool cyan/blue "scan" look.
    tinted[:, :, 2] = (tinted[:, :, 2] * 0.15).astype(tinted.dtype)
    return tinted


def capture_webcam_image(save_path: str = "", xray: bool = False) -> str:
    """Capture a single still frame from the default webcam and save it
    as a PNG, optionally with the stylized X-ray-vision effect applied."""
    try:
        cv2, frame = _capture_frame()
    except RuntimeError as e:
        return str(e)

    if xray:
        frame = _apply_xray_effect(cv2, frame)

    target = (
        Path(save_path).expanduser()
        if save_path
        else Path(tempfile.gettempdir()) / "jarvis_webcam.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    if not cv2.imwrite(str(target), frame):
        return f"Could not write the captured frame to '{target}'."

    label = "X-ray-style webcam capture" if xray else "Webcam capture"
    return f"{label} saved to '{target}'."


def describe_webcam(question: str = "", xray: bool = False) -> str:
    """Capture a frame from the webcam and describe it (or answer a
    question about it) using the local vision model, optionally applying
    the stylized X-ray effect first. The frame is never saved to disk."""
    try:
        cv2, frame = _capture_frame()
    except RuntimeError as e:
        return str(e)

    if xray:
        frame = _apply_xray_effect(cv2, frame)

    question = (question or "").strip() or DEFAULT_QUESTION

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        if not cv2.imwrite(tmp_path, frame):
            return "Could not prepare the captured frame for the vision model."

        client = Client(host="http://localhost:11434")
        response = client.chat(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": question,
                    "images": [tmp_path],
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
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass


WEBCAM_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "capture_webcam_image",
            "description": (
                "Capture a single still frame from the default webcam and "
                "save it as a PNG file. Writes to the filesystem and opens "
                "the camera briefly, so this requires confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "save_path": {
                        "type": "string",
                        "description": (
                            "Where to save the capture. Defaults to a temp "
                            "file if omitted."
                        ),
                    },
                    "xray": {
                        "type": "boolean",
                        "description": (
                            "Apply a stylized 'X-ray vision' edge/invert/tint "
                            "effect to the capture. This is a visual filter, "
                            "not real X-ray or thermal imaging."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_webcam",
            "description": (
                "Capture a frame from the webcam and describe what's visible "
                "(or answer a specific question about it) using the local "
                "vision model, without saving a file. Set xray=true to run "
                "the description against the stylized X-ray-filtered frame "
                "instead of the plain one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A specific question to ask about what the camera sees. Defaults to a general description.",
                    },
                    "xray": {
                        "type": "boolean",
                        "description": "Describe the stylized X-ray-filtered frame instead of the plain one.",
                    },
                },
                "required": [],
            },
        },
    },
]

WEBCAM_TOOL_FUNCTIONS = {
    "capture_webcam_image": capture_webcam_image,
    "describe_webcam": describe_webcam,
}

# capture_webcam_image writes a file; describe_webcam opens the physical
# camera (a stronger privacy boundary than reading an already-displayed
# screen) even though it writes nothing persistent -- see module docstring.
WEBCAM_RISKY_TOOLS = {"capture_webcam_image", "describe_webcam"}
