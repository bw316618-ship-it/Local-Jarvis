"""
Central configuration for Jarvis.

Defaults live here. To override any of them without editing code, copy
jarvis_config.example.json to jarvis_config.json at the project root and
change just the keys you want -- anything you don't specify keeps its
default. jarvis_config.json is gitignored, so personal tweaks (e.g. a
different Ollama model, custom indexed folders) don't get committed.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
USER_CONFIG_PATH = BASE_DIR / "jarvis_config.json"

DEFAULTS = {
    # brain/llm.py
    "model": "qwen3:4b",
    "num_ctx": 8192,
    "max_tool_rounds": 15,
    "short_term_turns": 6,     # NEW: how many recent (user, jarvis) turn pairs stay verbatim in context
    # voice/voice.py
    "whisper_model": "base.en",
    "voice_listen_seconds": 6,
    "voice_silence_seconds": 1.2,
    "voice_max_wait_seconds": 6,
    "voice_max_recording_seconds": 30,
    # voice/wake_word.py
    "wake_word_threshold": 0.5,
    # tools/system.py, tools/git_tools.py
    "command_timeout_seconds": 30,
    # tools/file_index.py -- index_roots: null means use the built-in
    # Documents/Desktop/Downloads default; set a list of paths to override.
    "index_roots": None,
    "index_chunk_size": 500,
    "index_chunk_overlap": 50,
    "index_max_file_mb": 20,
    "piper_voice_model": "voices/en_US-amy-medium.onnx",
    # tools/routing.py -- free API key from https://openrouteservice.org/dev/#/signup
    # (needed for walking/cycling directions; without it, get_route falls
    # back to the keyless OSRM demo server, which only reliably serves
    # driving directions)
    "ors_api_key": None,
    # ui/hud_server.py -- ports for the local graphical HUD (toggled via
    # /hud). Only need to change these if something else on the machine
    # is already using 8765/8766.
    "hud_http_port": 8765,
    "hud_ws_port": 8766,
}


def _load_user_overrides() -> dict:
    if not USER_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Jarvis config] Could not read jarvis_config.json, using defaults: {e}")
        return {}


def _build_config() -> dict:
    config = dict(DEFAULTS)
    overrides = _load_user_overrides()

    unknown_keys = set(overrides) - set(DEFAULTS)
    if unknown_keys:
        print(f"[Jarvis config] Ignoring unknown config keys: {sorted(unknown_keys)}")

    for key, value in overrides.items():
        if key in DEFAULTS:
            config[key] = value

    return config


CONFIG = _build_config()
