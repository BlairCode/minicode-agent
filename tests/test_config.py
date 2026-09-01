from pathlib import Path

import pytest

from minicode_agent.config import ConfigError, load_config


def test_default_configuration_prefers_qwen() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "default.yaml")
    assert config.model.provider == "qwen"
    assert config.model.model == "qwen-plus"
    assert config.model.api_key_env == "DASHSCOPE_API_KEY"
    assert config.model.request_timeout == 120
    assert "dashscope.aliyuncs.com" in (config.model.base_url or "")


def test_runtime_limits_can_be_overridden_by_environment(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MINICODE_REQUEST_TIMEOUT", "45.5")
    monkeypatch.setenv("MINICODE_MAX_STEPS", "12")
    monkeypatch.setenv("MINICODE_CONTEXT_CHAR_BUDGET", "16000")
    monkeypatch.setenv("MINICODE_COMMAND_TIMEOUT", "8")

    config = load_config(root / "config" / "default.yaml")

    assert config.model.request_timeout == 45.5
    assert config.agent.max_steps == 12
    assert config.agent.context_char_budget == 16000
    assert config.security.command_timeout == 8


def test_invalid_numeric_environment_override_is_reported(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MINICODE_MAX_STEPS", "many")
    with pytest.raises(ConfigError, match="MINICODE_MAX_STEPS must be an integer"):
        load_config(root / "config" / "default.yaml")
