"""tools/webcam.py -- capture_webcam_image and describe_webcam, including
the opencv-missing and camera-unavailable degrade paths and the X-ray
stylization branch.

cv2 is imported lazily inside tools.webcam, so tests patch builtins.__import__
to simulate it being missing, and otherwise construct a fake cv2 module
(MagicMock) rather than requiring a real camera/opencv install.
"""

import builtins
from unittest.mock import MagicMock, patch

import tools.webcam as webcam


def _fake_cv2_with_camera(frame_ok=True):
    """A MagicMock standing in for the cv2 module, wired so
    VideoCapture(0) opens, reads a frame, and releases cleanly."""
    cv2 = MagicMock()
    camera = MagicMock()
    camera.isOpened.return_value = True
    if frame_ok:
        camera.read.return_value = (True, "FAKE_FRAME")
    else:
        camera.read.return_value = (False, None)
    cv2.VideoCapture.return_value = camera
    cv2.imwrite.return_value = True
    return cv2, camera


def _patch_cv2_import(cv2_module):
    """tools.webcam does `import cv2` inside functions -- patch the
    actual import machinery so that import resolves to our fake module."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            return cv2_module
        return real_import(name, *args, **kwargs)

    return patch.object(builtins, "__import__", side_effect=fake_import)


def test_capture_webcam_image_reports_missing_opencv():
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        result = webcam.capture_webcam_image()

    assert "opencv-python" in result.lower()


def test_capture_webcam_image_reports_camera_not_opening():
    cv2 = MagicMock()
    camera = MagicMock()
    camera.isOpened.return_value = False
    cv2.VideoCapture.return_value = camera

    with _patch_cv2_import(cv2):
        result = webcam.capture_webcam_image()

    assert "could not open the webcam" in result.lower()
    camera.release.assert_called()


def test_capture_webcam_image_reports_no_frame_returned():
    cv2, camera = _fake_cv2_with_camera(frame_ok=False)

    with _patch_cv2_import(cv2):
        result = webcam.capture_webcam_image()

    assert "did not return a frame" in result.lower()


def test_capture_webcam_image_saves_to_requested_path(tmp_path):
    cv2, camera = _fake_cv2_with_camera()
    target = tmp_path / "shot.png"

    with _patch_cv2_import(cv2):
        result = webcam.capture_webcam_image(save_path=str(target))

    assert str(target) in result
    cv2.imwrite.assert_called_once()
    written_path = cv2.imwrite.call_args[0][0]
    assert written_path == str(target)
    # Camera released after the single capture, never left running.
    camera.release.assert_called()


def test_capture_webcam_image_xray_applies_effect_before_saving(tmp_path):
    cv2, camera = _fake_cv2_with_camera()
    cv2.cvtColor.return_value = "GRAY"
    cv2.Canny.return_value = "EDGES"
    cv2.bitwise_not.return_value = "INVERTED"

    import numpy as np
    tinted = np.zeros((2, 2, 3), dtype="uint8")
    cv2.COLOR_GRAY2BGR = "COLOR_GRAY2BGR"
    cv2.cvtColor.side_effect = ["GRAY", tinted]

    with _patch_cv2_import(cv2):
        result = webcam.capture_webcam_image(save_path=str(tmp_path / "x.png"), xray=True)

    assert "X-ray" in result
    cv2.Canny.assert_called_once()
    cv2.bitwise_not.assert_called_once()
    # The frame actually written should be the tinted/processed one, not
    # the raw "FAKE_FRAME" string.
    written_frame = cv2.imwrite.call_args[0][1]
    assert written_frame is tinted


def test_describe_webcam_does_not_persist_a_file(tmp_path, monkeypatch):
    cv2, camera = _fake_cv2_with_camera()

    fake_client = MagicMock()
    fake_client.chat.return_value = {"message": {"content": "A desk with a lamp."}}

    with _patch_cv2_import(cv2), patch("tools.webcam.Client", return_value=fake_client):
        result = webcam.describe_webcam()

    assert result == "A desk with a lamp."
    # imwrite was called against a temp path, and that temp path is
    # cleaned up -- confirm nothing lingers where the test could see it.
    temp_path_used = cv2.imwrite.call_args[0][0]
    from pathlib import Path
    assert not Path(temp_path_used).exists()


def test_describe_webcam_reports_when_ollama_unreachable():
    cv2, camera = _fake_cv2_with_camera()

    fake_client = MagicMock()
    fake_client.chat.side_effect = ConnectionError("no server")

    with _patch_cv2_import(cv2), patch("tools.webcam.Client", return_value=fake_client):
        result = webcam.describe_webcam()

    assert "vision isn't available" in result.lower()
    assert "ollama pull" in result.lower()


def test_webcam_tools_are_registered_risky():
    from tools.webcam import WEBCAM_RISKY_TOOLS
    assert "capture_webcam_image" in WEBCAM_RISKY_TOOLS
    assert "describe_webcam" in WEBCAM_RISKY_TOOLS
