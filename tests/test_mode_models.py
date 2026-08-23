"""Tests for per-mode model override (CONFIG["mode_models"]).

Lets e.g. CODING mode use a coding-specialized Ollama model without
switching companion/creative conversations to it too. Covers the
precedence rule in config.get_model_for_mode and brain/llm.py's chat()
actually resolving self.model from the active mode on every turn.
"""

from unittest.mock import MagicMock

import config as config_module
from brain.llm import JarvisLLM
from brain.mode_config import CODING, COMPANION, CREATIVE, NORMAL
from config import get_model_for_mode
from voice import session_state


def setup_function():
    session_state.set_mode(NORMAL)


def teardown_function():
    session_state.set_mode(NORMAL)


def make_jarvis():
    jarvis = JarvisLLM.__new__(JarvisLLM)
    jarvis.confirm_callback = lambda name, args: True
    jarvis.system_prompt = "TASK"
    jarvis.companion_system_prompt = "COMPANION"
    jarvis.model = "placeholder"
    jarvis.memory = MagicMock()
    jarvis.short_term = []
    return jarvis


def _stream(content, tool_calls=None):
    return iter([{"message": {"content": content, "tool_calls": tool_calls}}])


# --- config.get_model_for_mode precedence -------------------------------

def test_falls_back_to_default_model_when_mode_not_listed(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {})
    monkeypatch.setitem(config_module.CONFIG, "model", "qwen3:4b")
    assert get_model_for_mode(CODING) == "qwen3:4b"


def test_uses_mode_specific_model_when_configured(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {"coding": "qwen2.5-coder:7b"})
    monkeypatch.setitem(config_module.CONFIG, "model", "qwen3:4b")
    assert get_model_for_mode(CODING) == "qwen2.5-coder:7b"
    # Modes not listed still fall back to the default.
    assert get_model_for_mode(COMPANION) == "qwen3:4b"


def test_explicit_override_always_wins(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {"coding": "qwen2.5-coder:7b"})
    assert get_model_for_mode(CODING, explicit="my-forced-model") == "my-forced-model"


# --- JarvisLLM instance attribute safety --------------------------------

def test_new_constructed_instance_has_a_safe_explicit_override_default():
    """JarvisLLM.__new__(JarvisLLM) skips __init__ entirely -- used
    throughout the test suite's make_jarvis() helpers. Without a class-level
    default, chat()'s self._explicit_model_override lookup would
    AttributeError on every one of those test doubles."""
    jarvis = JarvisLLM.__new__(JarvisLLM)
    assert jarvis._explicit_model_override is None


def test_init_stores_the_explicit_override_separately_from_resolved_model():
    # ollama.Client() only opens a connection lazily on first real call, so
    # constructing it doesn't require a live server -- safe to build a real
    # JarvisLLM here rather than needing to mock the client just to check
    # __init__ stored the constructor arg correctly.
    jarvis = JarvisLLM(model="pinned-model")
    assert jarvis._explicit_model_override == "pinned-model"
    assert jarvis.model == "pinned-model"


# --- chat() resolves the right model per turn ---------------------------

def _patch_common_chat_deps(monkeypatch, jarvis, streamed_reply="ok"):
    import brain.llm as llm_module

    fake_client = MagicMock()
    fake_client.chat.side_effect = (
        lambda model, messages, tools=None, stream=False, **kwargs: _stream(streamed_reply, None)
    )
    jarvis.client = fake_client

    monkeypatch.setattr(llm_module, "remember_turn", lambda u, r: None)
    monkeypatch.setattr(llm_module, "recall", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(llm_module, "recall_facts", lambda q, k=3, **kwargs: [])
    monkeypatch.setattr(
        llm_module, "get_embedder", lambda: MagicMock(encode=lambda q: MagicMock(tolist=lambda: [0.0]))
    )
    return fake_client


def test_chat_uses_mode_specific_model_for_coding(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {"coding": "qwen2.5-coder:7b"})
    monkeypatch.setitem(config_module.CONFIG, "model", "qwen3:4b")

    jarvis = make_jarvis()
    fake_client = _patch_common_chat_deps(monkeypatch, jarvis)

    session_state.set_mode(CODING)
    jarvis.chat("write a function", on_step=lambda m: None)

    used_model = fake_client.chat.call_args.kwargs.get("model") or fake_client.chat.call_args.args[0]
    assert used_model == "qwen2.5-coder:7b"
    assert jarvis.model == "qwen2.5-coder:7b"


def test_chat_uses_default_model_for_normal_when_no_override_configured(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {"coding": "qwen2.5-coder:7b"})
    monkeypatch.setitem(config_module.CONFIG, "model", "qwen3:4b")

    jarvis = make_jarvis()
    fake_client = _patch_common_chat_deps(monkeypatch, jarvis)

    session_state.set_mode(NORMAL)
    jarvis.chat("hello there, what's the weather like", on_step=lambda m: None)

    used_model = fake_client.chat.call_args.kwargs.get("model") or fake_client.chat.call_args.args[0]
    assert used_model == "qwen3:4b"


def test_chat_respects_explicit_constructor_override_over_mode_models(monkeypatch):
    monkeypatch.setitem(config_module.CONFIG, "mode_models", {"coding": "qwen2.5-coder:7b"})

    jarvis = make_jarvis()
    jarvis._explicit_model_override = "user-pinned-model"
    fake_client = _patch_common_chat_deps(monkeypatch, jarvis)

    session_state.set_mode(CODING)
    jarvis.chat("write a function", on_step=lambda m: None)

    used_model = fake_client.chat.call_args.kwargs.get("model") or fake_client.chat.call_args.args[0]
    assert used_model == "user-pinned-model"
