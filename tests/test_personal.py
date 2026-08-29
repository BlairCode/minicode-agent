from __future__ import annotations

import json

from minicode_agent.personal import (
    CredentialStore,
    HistoryRepository,
    PersonalSettings,
    PersonalSettingsStore,
)
from minicode_agent.session import SessionRecorder


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def test_personal_settings_are_external_and_contain_no_api_key(tmp_path) -> None:
    store = PersonalSettingsStore(tmp_path / "user-data")
    settings = PersonalSettings(workspace=str(tmp_path / "workspace"), code_style="pep8")
    store.save(settings)
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["code_style"] == "pep8"
    assert payload["request_timeout"] == 120
    assert all("key" not in name.lower() for name in payload)
    assert store.load(PersonalSettings()).workspace == str(tmp_path / "workspace")


def test_credential_store_uses_keyring_backend() -> None:
    backend = MemoryKeyring()
    store = CredentialStore(backend)
    store.set("qwen", "dashscope-secret")
    assert store.get("qwen") == "dashscope-secret"
    store.delete("qwen")
    assert store.get("qwen") is None


def test_history_repository_reads_external_jsonl(tmp_path) -> None:
    recorder = SessionRecorder(tmp_path / "sessions")
    recorder.start("a" * 32)
    recorder.record("run_started", {"task": "Fix calculator", "agent": "coding"})
    recorder.record("run_finished", {"state": "COMPLETED"})
    history = HistoryRepository(tmp_path)
    sessions = history.list_sessions()
    assert sessions[0]["task"] == "Fix calculator"
    assert sessions[0]["state"] == "COMPLETED"
