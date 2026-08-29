from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(slots=True)
class ModelConfig:
    provider: str = "qwen"
    model: str = "qwen-plus"
    base_url: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "DASHSCOPE_API_KEY"
    temperature: float = 0.2
    max_tokens: int = 8192
    request_timeout: float = 120.0
    max_retries: int = 2


@dataclass(slots=True)
class AgentConfig:
    default: str = "coding"
    max_steps: int = 30
    max_tool_errors: int = 5
    context_char_budget: int = 100_000
    retry_base_seconds: float = 0.5


@dataclass(slots=True)
class WorkspaceConfig:
    root: str = "./workspace"
    allow_outside_workspace: bool = False
    backup_before_overwrite: bool = False
    max_read_bytes: int = 1_000_000
    max_tool_output_chars: int = 20_000


@dataclass(slots=True)
class CodingConfig:
    default_language: str = "auto"
    code_style: str = "auto"
    comment_level: str = "minimal"
    comment_language: str = "chinese"
    prefer_existing_style: bool = True


@dataclass(slots=True)
class SecurityConfig:
    command_mode: str = "ask"
    command_timeout: float = 30.0
    network_access: bool = False


@dataclass(slots=True)
class LeetCodeConfig:
    language: str = "cpp"
    mode: str = "interview"
    generate_tests: bool = True
    save_solution: bool = True
    save_explanation: bool = True
    include_complexity: bool = True


@dataclass(slots=True)
class UIConfig:
    show_tool_calls: bool = True
    show_command_output: bool = True
    web_port: int = 8765
    open_browser: bool = True


@dataclass(slots=True)
class StorageConfig:
    data_dir: str | None = None
    keep_history: bool = True


@dataclass(slots=True)
class AppConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    coding: CodingConfig = field(default_factory=CodingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    leetcode: LeetCodeConfig = field(default_factory=LeetCodeConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def validate(self) -> None:
        if self.model.provider not in {"qwen", "openai-compatible"}:
            raise ConfigError("model.provider must be qwen or openai-compatible")
        if not self.model.model.strip():
            raise ConfigError("model.model cannot be empty")
        if not 0 <= self.model.temperature <= 2:
            raise ConfigError("model.temperature must be between 0 and 2")
        if self.model.max_tokens < 1 or self.model.max_retries < 0:
            raise ConfigError("model token and retry limits must be non-negative")
        if not 10 <= self.model.request_timeout <= 600:
            raise ConfigError("model.request_timeout must be between 10 and 600 seconds")
        if self.agent.max_steps < 1 or self.agent.max_tool_errors < 1:
            raise ConfigError("agent limits must be positive")
        if self.agent.context_char_budget < 4_000:
            raise ConfigError("agent.context_char_budget must be at least 4000")
        if self.workspace.max_read_bytes < 1 or self.workspace.max_tool_output_chars < 500:
            raise ConfigError("workspace size limits are too small")
        if self.security.command_mode not in {"strict", "ask", "full"}:
            raise ConfigError("security.command_mode must be strict, ask, or full")
        if self.security.command_timeout <= 0:
            raise ConfigError("security.command_timeout must be positive")
        if self.agent.default not in {"coding", "leetcode"}:
            raise ConfigError("agent.default must be coding or leetcode")
        if self.leetcode.mode not in {"solve", "hint", "interview", "review"}:
            raise ConfigError("leetcode.mode must be solve, hint, interview, or review")
        if self.coding.code_style not in {"auto", "google", "pep8", "llvm", "microsoft"}:
            raise ConfigError("coding.code_style is invalid")
        if self.coding.comment_level not in {"none", "minimal", "normal", "detailed"}:
            raise ConfigError("coding.comment_level is invalid")
        if not 0 <= self.ui.web_port <= 65535:
            raise ConfigError("ui.web_port must be between 0 and 65535")


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigError(f"configuration file not found: {path}")
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    return value


def _section(cls: type, values: Mapping[str, Any] | None):
    if values is not None and not isinstance(values, Mapping):
        raise ConfigError(f"{cls.__name__} configuration must be a mapping")
    values = dict(values or {})
    allowed = cls.__dataclass_fields__.keys()
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise ConfigError(f"unknown {cls.__name__} fields: {', '.join(unknown)}")
    try:
        return cls(**values)
    except TypeError as exc:
        raise ConfigError(str(exc)) from exc


def load_config(
    default_path: str | Path = "config/default.yaml",
    user_path: str | Path | None = None,
) -> AppConfig:
    data = _read_yaml(Path(default_path), required=True)
    if user_path:
        data = _merge(data, _read_yaml(Path(user_path), required=True))

    env_overrides: dict[str, dict[str, Any]] = {}
    if model := os.getenv("MINICODE_MODEL"):
        env_overrides.setdefault("model", {})["model"] = model
    if base_url := os.getenv("MINICODE_BASE_URL"):
        env_overrides.setdefault("model", {})["base_url"] = base_url
    if workspace := os.getenv("MINICODE_WORKSPACE"):
        env_overrides.setdefault("workspace", {})["root"] = workspace
    if mode := os.getenv("MINICODE_COMMAND_MODE"):
        env_overrides.setdefault("security", {})["command_mode"] = mode.lower()
    data = _merge(data, env_overrides)

    allowed_sections = {
        "model",
        "agent",
        "workspace",
        "coding",
        "security",
        "leetcode",
        "ui",
        "storage",
    }
    unknown_sections = sorted(set(data) - allowed_sections)
    if unknown_sections:
        raise ConfigError(f"unknown configuration sections: {', '.join(unknown_sections)}")

    config = AppConfig(
        model=_section(ModelConfig, data.get("model")),
        agent=_section(AgentConfig, data.get("agent")),
        workspace=_section(WorkspaceConfig, data.get("workspace")),
        coding=_section(CodingConfig, data.get("coding")),
        security=_section(SecurityConfig, data.get("security")),
        leetcode=_section(LeetCodeConfig, data.get("leetcode")),
        ui=_section(UIConfig, data.get("ui")),
        storage=_section(StorageConfig, data.get("storage")),
    )
    config.validate()
    return config
