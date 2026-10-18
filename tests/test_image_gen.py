"""tools/image_gen.py -- generate_image's success path, input clamping,
and the degrade paths when no local AUTOMATIC1111 server is reachable."""

import base64
from unittest.mock import MagicMock, patch

import requests

import tools.image_gen as image_gen


# A 1x1 transparent PNG, valid enough to round-trip through base64 decode.
_TINY_PNG_B64 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15"
        "c4890000000a49444154789c6360000002000100ffff03000006000557bfab"
        "d40000000049454e44ae426082"
    )
).decode()


def test_generate_image_requires_a_prompt():
    result = image_gen.generate_image("")
    assert "prompt is required" in result.lower()


def test_generate_image_reports_connection_error_with_actionable_message():
    with patch("tools.image_gen.requests.post", side_effect=requests.exceptions.ConnectionError()):
        result = image_gen.generate_image("a red fox")

    assert "no automatic1111 server found" in result.lower()
    assert "127.0.0.1:7860" in result


def test_generate_image_reports_timeout():
    with patch("tools.image_gen.requests.post", side_effect=requests.exceptions.Timeout()):
        result = image_gen.generate_image("a red fox")

    assert "timed out" in result.lower()


def test_generate_image_saves_decoded_png(tmp_path):
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"images": [_TINY_PNG_B64]}

    target = tmp_path / "fox.png"

    with patch("tools.image_gen.requests.post", return_value=fake_response) as post:
        result = image_gen.generate_image("a red fox", save_path=str(target))

    assert str(target) in result
    assert target.exists()
    assert target.read_bytes().startswith(b"\x89PNG")

    # Confirm the prompt and clamped defaults were actually sent.
    _, kwargs = post.call_args
    payload = kwargs["json"]
    assert payload["prompt"] == "a red fox"
    assert payload["width"] == 512
    assert payload["height"] == 512
    assert payload["steps"] == 20


def test_generate_image_clamps_out_of_range_dimensions_and_steps():
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"images": [_TINY_PNG_B64]}

    with patch("tools.image_gen.requests.post", return_value=fake_response) as post:
        image_gen.generate_image("a red fox", width=4, height=99999, steps=0)

    _, kwargs = post.call_args
    payload = kwargs["json"]
    assert payload["width"] == 64
    assert payload["height"] == 1536
    assert payload["steps"] == 1


def test_generate_image_reports_empty_image_list():
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"images": []}

    with patch("tools.image_gen.requests.post", return_value=fake_response):
        result = image_gen.generate_image("a red fox")

    assert "no image" in result.lower()


def test_generate_image_uses_configured_url(monkeypatch):
    monkeypatch.setitem(image_gen.CONFIG, "automatic1111_url", "http://192.168.1.50:7860")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"images": [_TINY_PNG_B64]}

    with patch("tools.image_gen.requests.post", return_value=fake_response) as post:
        image_gen.generate_image("a red fox")

    url = post.call_args[0][0]
    assert url == "http://192.168.1.50:7860/sdapi/v1/txt2img"


def test_generate_image_is_registered_risky():
    from tools.image_gen import IMAGE_GEN_RISKY_TOOLS
    assert "generate_image" in IMAGE_GEN_RISKY_TOOLS
