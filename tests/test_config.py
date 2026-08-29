from pathlib import Path

from minicode_agent.config import load_config


def test_default_configuration_prefers_qwen() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "default.yaml")
    assert config.model.provider == "qwen"
    assert config.model.model == "qwen-plus"
    assert config.model.api_key_env == "DASHSCOPE_API_KEY"
    assert config.model.request_timeout == 120
    assert "dashscope.aliyuncs.com" in (config.model.base_url or "")
