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
    # 4096 silently truncated instructions/context on longer turns --
    # the highest-impact lever identified before any prompt tuning.
    # 8192 roughly doubles headroom for tool results + recalled memory
    # + the system prompt to all fit without the oldest, often most
    # relevant, content getting pushed out first.
    "num_ctx": 8192,
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

    # Memory retrieval. recall()/recall_facts() used to return their
    # top-k nearest neighbors unconditionally -- once the store held
    # more than a handful of turns/facts, "top-3 closest" could still
    # mean "3 barely-related results" once nothing genuinely relevant
    # existed, and that noise got stuffed into the prompt as if it were
    # signal. This is a cosine-similarity floor (0.0-1.0, higher =
    # stricter) applied after the nearest-neighbor query: a candidate
    # below it is dropped rather than returned just because it was the
    # closest thing available. 0.35 is a conservative starting point
    # for all-MiniLM-L6-v2 (memory/shared.py) -- raise it if recall
    # still feels noisy, lower it if genuinely relevant memories are
    # being dropped.
    "memory_relevance_threshold": 0.35,

    # Streaming.
    "streaming": True,

    # Ollama generation settings.
    "temperature": 0.2,
    "top_p": 0.9,

    "piper_voice_model": "voices/en_US-amy-medium.onnx",

    # Maps.
    "ors_api_key": None,

    # Model tiers. "model" is the daily-driver default (small/fast,
    # matched to the 6GB-VRAM Nitro V15 constraint); "heavy_model" is an
    # optional larger model the user can opt into per-session via the
    # /brain heavy command or enter_heavy_brain tool (see
    # voice/session_state.py, tools/session_control.py). Defaults to
    # qwen3:8b rather than the None it used to be -- with no default,
    # the heavy-brain toggle silently did nothing (get_model_for_mode
    # falls back to the fast tier whenever heavy_model is unset), so
    # every /brain heavy or enter_heavy_brain call was a no-op until the
    # user hand-edited jarvis_config.json. qwen3:8b, not qwen2.5:14b, is
    # the default specifically because of the 6GB-VRAM constraint above
    # -- 14b would likely spill out of VRAM and make "heavy" slower than
    # it's worth. Unlike ors_api_key, there's no runtime fallback if
    # qwen3:8b isn't actually pulled in Ollama -- Ollama itself will
    # error on first use; `ollama pull qwen3:8b` before relying on
    # /brain heavy, or override this key if a different model is
    # preferred.
    "heavy_model": "qwen3:8b",

    # Network tool retry (web search, weather, routing, nearby-place,
    # geocoding/IP-location lookups). Only retryable failures are retried
    # -- see tools/net.py:is_retryable -- so a bad query or 404 fails once,
    # not network_retry_attempts times.
    "network_retry_attempts": 3,
    "network_retry_backoff_seconds": 0.5,

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


def get_model_for_mode(mode: str, explicit: str = None, heavy: bool = False) -> str:
    """Resolve which Ollama model a chat turn should use.

    Precedence, highest first:
      1. `explicit` -- passed straight into JarvisLLM(model=...) at
         construction time. Wins over everything else regardless of mode
         or the heavy-brain flag.
      2. Heavy brain -- if `heavy` is True and "heavy_model" is
         configured, that model is used no matter which interaction mode
         (normal/companion/creative/coding) is active. This is
         deliberately orthogonal to mode_models below: heavy brain is a
         "use your best model for this" toggle the user flips per
         session (see voice/session_state.py's brain-tier state), not
         something tied to a particular mode the way e.g. a
         coding-specialized model is.
      3. CONFIG["mode_models"][mode] -- a mode-specific model.
      4. CONFIG["model"] -- the default daily-driver model.

    If heavy=True but no "heavy_model" is configured, falls through to
    (3)/(4) rather than erroring, same as an unset ors_api_key falling
    back to OSRM instead of failing outright.
    """
    if explicit:
        return explicit

    if heavy:
        heavy_model = CONFIG.get("heavy_model")
        if heavy_model:
            return heavy_model

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
