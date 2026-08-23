"""
Central configuration for Jarvis.

Performance-oriented defaults:
- small active context
- short tool loops
- aggressive tool filtering
- persistent model process handled by Ollama
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
USER_CONFIG_PATH = BASE_DIR / "jarvis_config.json"

DEFAULTS = {
    # Fast local model.
    "model": "qwen3:4b",
    "mode_models": {},
    "num_ctx": 4096,
    "max_tool_rounds": 8,
    "short_term_turns": 4,

    # Voice.
    "whisper_model": "base.en",
    "voice_listen_seconds": 6,
    "voice_silence_seconds": 1.2,
    "voice_max_wait_seconds": 6,
    "voice_max_recording_seconds": 30,
    "wake_word_threshold": 0.5,
    "command_timeout_seconds": 30,
    "tool_call_timeout_seconds": 30,

    # Retrieval.
    "index_roots": None,
    "index_chunk_size": 500,
    "index_chunk_overlap": 50,
    "index_max_file_mb": 20,
    # Tool filtering.
    "tool_relevance_threshold": 20,
    "tool_relevance_top_k": 12,

    # Streaming.
    "streaming": True,

    # Ollama generation settings.
    "temperature": 0.2,
    "top_p": 0.9,

    "piper_voice_model": "voices/en_US-amy-medium.onnx",

    # Maps.
    "ors_api_key": None,

    # HUD.
    "hud_http_port": 8765,
    "hud_ws_port": 8766,
    "hud_system_status_interval_seconds": 5,
    "backend_ws_port": 8770,

    # Security.
    "device_auth_file": "data/trusted_devices.json",
}


def _load_user_overrides() -> dict:
    if not USER_CONFIG_PATH.exists():
        return {}

    try:
        return json.loads(
            USER_CONFIG_PATH.read_text(encoding="utf-8")
        )
    except Exception as e:
        print(
            "[Jarvis config] Could not read jarvis_config.json, "
            f"using defaults: {e}"
        )
        return {}


def _build_config() -> dict:
    config = dict(DEFAULTS)
    overrides = _load_user_overrides()

    unknown_keys = set(overrides) - set(DEFAULTS)

    if unknown_keys:
        print(
            "[Jarvis config] Ignoring unknown config keys: "
            f"{sorted(unknown_keys)}"
        )

    for key, value in overrides.items():
        if key in DEFAULTS:
            config[key] = value

    return config


def get_index_roots() -> list[str]:
    configured = CONFIG.get("index_roots")
    if configured:
        return list(configured)

    return [
        str(Path.home() / "Documents"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Downloads"),
    ]


def get_model_for_mode(mode: str, explicit: str = None) -> str:
    if explicit:
        return explicit

    return (
        CONFIG.get("mode_models", {}).get(mode)
        or CONFIG["model"]
    )


def get_chat_options() -> dict:
    """
    Options shared by all normal inference calls.
    """

    return {
        "num_ctx": CONFIG["num_ctx"],
        "temperature": CONFIG["temperature"],
        "top_p": CONFIG["top_p"],
    }


CONFIG = _build_config()
