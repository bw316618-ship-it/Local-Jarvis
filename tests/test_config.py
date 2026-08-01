"""Config: defaults, user overrides, unknown-key warnings, malformed JSON."""

import json

import config


def test_defaults_used_when_no_override_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "jarvis_config.json")
    result = config._build_config()
    assert result == config.DEFAULTS


def test_override_replaces_only_the_given_key(tmp_path, monkeypatch):
    override_path = tmp_path / "jarvis_config.json"
    override_path.write_text(json.dumps({"model": "qwen3:70b"}))
    monkeypatch.setattr(config, "USER_CONFIG_PATH", override_path)

    result = config._build_config()
    assert result["model"] == "qwen3:70b"
    assert result["max_tool_rounds"] == config.DEFAULTS["max_tool_rounds"]


def test_unknown_keys_are_ignored_not_crashed_on(tmp_path, monkeypatch, capsys):
    override_path = tmp_path / "jarvis_config.json"
    override_path.write_text(json.dumps({"totally_unknown_key": "value"}))
    monkeypatch.setattr(config, "USER_CONFIG_PATH", override_path)

    result = config._build_config()
    assert "totally_unknown_key" not in result
    assert result == config.DEFAULTS


def test_malformed_json_falls_back_to_defaults(tmp_path, monkeypatch):
    override_path = tmp_path / "jarvis_config.json"
    override_path.write_text("{ not valid json")
    monkeypatch.setattr(config, "USER_CONFIG_PATH", override_path)

    result = config._build_config()
    assert result == config.DEFAULTS
