from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Protocol

from minicode_agent.config import AppConfig


APP_NAME = "MiniCodeAgent"


def user_data_directory(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return (Path(base) / APP_NAME).resolve()
    if os.sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()
    base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "minicode-agent").resolve()


@dataclass(slots=True)
class PersonalSettings:
    provider: str = "qwen"
    model: str = "qwen-plus"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    request_timeout: float = 120.0
    workspace: str = ""
    command_mode: str = "ask"
    network_access: bool = False
    code_style: str = "auto"
    comment_level: str = "minimal"
    default_language: str = "auto"
    leetcode_language: str = "cpp"
    leetcode_mode: str = "interview"

    def apply(self, config: AppConfig) -> None:
        config.model.provider = self.provider
        config.model.model = self.model
        config.model.base_url = self.base_url or None
        config.model.request_timeout = float(self.request_timeout)
        config.model.api_key_env = "DASHSCOPE_API_KEY" if self.provider == "qwen" else "OPENAI_API_KEY"
        if self.workspace:
            config.workspace.root = self.workspace
        config.security.command_mode = self.command_mode
        config.security.network_access = self.network_access
        config.coding.code_style = self.code_style
        config.coding.comment_level = self.comment_level
        config.coding.default_language = self.default_language
        config.leetcode.language = self.leetcode_language
        config.leetcode.mode = self.leetcode_mode
        config.validate()

    @classmethod
    def from_config(cls, config: AppConfig) -> "PersonalSettings":
        return cls(
            provider=config.model.provider,
            model=config.model.model,
            base_url=config.model.base_url or "",
            request_timeout=config.model.request_timeout,
            workspace=config.workspace.root,
            command_mode=config.security.command_mode,
            network_access=config.security.network_access,
            code_style=config.coding.code_style,
            comment_level=config.coding.comment_level,
            default_language=config.coding.default_language,
            leetcode_language=config.leetcode.language,
            leetcode_mode=config.leetcode.mode,
        )


class PersonalSettingsStore:
    """Stores non-secret preferences outside the repository using atomic writes."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir / "settings.json"

    def load(self, defaults: PersonalSettings) -> PersonalSettings:
        if not self.path.exists():
            return defaults
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return defaults
        if not isinstance(payload, dict):
            return defaults
        allowed = {item.name for item in fields(PersonalSettings)}
        values = asdict(defaults)
        values.update({key: value for key, value in payload.items() if key in allowed})
        try:
            return PersonalSettings(**values)
        except TypeError:
            return defaults

    def save(self, settings: PersonalSettings) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.data_dir,
                prefix=".settings.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class CredentialStore:
    """Keeps API credentials in the operating-system credential backend."""

    SERVICE = "MiniCodeAgent"

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        if backend is None:
            try:
                import keyring
            except ImportError as exc:
                raise RuntimeError("keyring is required for secure API credential storage") from exc
            backend = keyring
        self.backend = backend

    @staticmethod
    def account(provider: str) -> str:
        return f"{provider}:api-key"

    def get(self, provider: str) -> str | None:
        try:
            return self.backend.get_password(self.SERVICE, self.account(provider))
        except Exception:
            return None

    def set(self, provider: str, secret: str) -> None:
        if not secret.strip():
            raise ValueError("API credential cannot be empty")
        self.backend.set_password(self.SERVICE, self.account(provider), secret.strip())

    def delete(self, provider: str) -> None:
        try:
            self.backend.delete_password(self.SERVICE, self.account(provider))
        except Exception:
            return


class HistoryRepository:
    def __init__(self, data_dir: str | Path) -> None:
        self.session_dir = Path(data_dir).resolve() / "sessions"

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.session_dir.exists():
            return []
        sessions: list[dict[str, Any]] = []
        try:
            paths = list(self.session_dir.glob("*.jsonl"))
        except OSError:
            return []
        paths.sort(key=self._modified_time, reverse=True)
        for path in paths[:limit]:
            events = self.load(path.stem)
            started = next((item for item in events if item.get("event") == "run_started"), None)
            finished = next((item for item in reversed(events) if item.get("event") == "run_finished"), None)
            if not started:
                continue
            payload = started.get("payload", {})
            sessions.append(
                {
                    "id": path.stem,
                    "task": str(payload.get("task", "Untitled task")),
                    "agent": str(payload.get("agent", "coding")),
                    "timestamp": started.get("timestamp", ""),
                    "state": (finished or {}).get("payload", {}).get("state", "RUNNING"),
                    "workspace_id": str(payload.get("workspace_id", "")),
                }
            )
        return sessions

    @staticmethod
    def _modified_time(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def load(self, session_id: str) -> list[dict[str, Any]]:
        if len(session_id) != 32 or any(
            char not in "0123456789abcdef" for char in session_id.lower()
        ):
            return []
        path = self.session_dir / f"{session_id}.jsonl"
        if not path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events
