"""ui/hud_server.py's _StaticFileHandler -- specifically, that .js/.mjs
get a hardcoded JavaScript Content-Type rather than falling through to
mimetypes.guess_type()'s platform-dependent (and on Windows,
registry-sourced) answer.

Root cause this guards against: SimpleHTTPRequestHandler.extensions_map
only hardcodes compression extensions, so .js falls through to
mimetypes.guess_type(). On a real, non-trivial number of Windows
machines that lookup returns something other than a JS MIME type (most
often text/plain) because the relevant registry key is missing or was
overwritten by other installed software. Classic <script src="...">
tags don't care and run fine regardless of Content-Type; type="module"
scripts (storm3d.js and everything it imports under vendor/three/) are
strictly rejected by the browser if the Content-Type isn't a JS MIME
type -- silently, from the Python server's point of view, since the
HTTP request itself still returns 200 OK.
"""

from unittest.mock import patch

import http.server

import ui.hud_server as hud_server_module


def test_js_gets_a_javascript_mime_type():
    assert hud_server_module._StaticFileHandler.extensions_map[".js"] == "text/javascript"


def test_mjs_gets_a_javascript_mime_type():
    assert hud_server_module._StaticFileHandler.extensions_map[".mjs"] == "text/javascript"


def test_js_mime_type_does_not_depend_on_mimetypes_guess_type():
    """Even if mimetypes.guess_type() would return something wrong --
    simulating the broken-Windows-registry case -- .js must still
    resolve correctly, because extensions_map is checked first."""
    handler = hud_server_module._StaticFileHandler.__new__(
        hud_server_module._StaticFileHandler
    )

    with patch.object(
        http.server.mimetypes,
        "guess_type",
        return_value=("text/plain", None),
    ):
        assert handler.guess_type("storm3d.js") == "text/javascript"
        assert handler.guess_type("vendor/three/three.module.js") == "text/javascript"


def test_compression_extensions_still_covered():
    """The fix extends SimpleHTTPRequestHandler's map rather than
    replacing it -- the handful of extensions it already hardcoded
    (gzip etc.) must survive."""
    assert hud_server_module._StaticFileHandler.extensions_map[".gz"] == "application/gzip"


def test_other_static_asset_types_have_explicit_types():
    mapping = hud_server_module._StaticFileHandler.extensions_map
    assert mapping[".css"] == "text/css"
    assert mapping[".json"] == "application/json"
    assert mapping[".svg"] == "image/svg+xml"
    assert mapping[".wasm"] == "application/wasm"


def test_http_server_uses_the_static_file_handler(monkeypatch):
    """_run_http_server must actually construct the fixed handler, not
    fall back to plain SimpleHTTPRequestHandler."""
    captured = {}

    class _FakeServer:
        def __init__(self, address, handler_factory):
            captured["handler_factory"] = handler_factory

        def serve_forever(self):
            pass

    monkeypatch.setattr(hud_server_module, "ThreadingHTTPServer", _FakeServer)

    bridge = hud_server_module.HUDBridge()
    bridge._run_http_server()

    handler_factory = captured["handler_factory"]
    # partial(...).func is the class it wraps
    assert handler_factory.func is hud_server_module._StaticFileHandler
