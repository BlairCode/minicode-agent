import json

from minicode_agent.session import SessionRecorder, redact
from minicode_agent.tools.command import _sanitized_environment


def test_recursive_redaction() -> None:
    value = redact({"api_key": "secret", "message": "Bearer abcdefghijklmno", "nested": ["sk-abcdefghijklmnop"]})
    assert value["api_key"] == "[REDACTED]"
    assert "Bearer" not in value["message"]
    assert value["nested"] == ["[REDACTED]"]


def test_session_is_jsonl(tmp_path) -> None:
    recorder = SessionRecorder(tmp_path)
    recorder.start("demo")
    recorder.record("event", {"ok": True})
    item = json.loads((tmp_path / "demo.jsonl").read_text(encoding="utf-8"))
    assert item["event"] == "event" and item["payload"]["ok"] is True


def test_session_write_failure_is_non_fatal(tmp_path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied", encoding="utf-8")
    recorder = SessionRecorder(blocked_parent / "sessions")
    recorder.start("a" * 32)
    recorder.record("event", {"ok": True})
    assert recorder.path is None
    assert recorder.last_error


def test_command_environment_removes_credentials(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret")
    monkeypatch.setenv("NORMAL_DEMO_VALUE", "visible")
    environment = _sanitized_environment()
    assert "DASHSCOPE_API_KEY" not in environment
    assert environment["NORMAL_DEMO_VALUE"] == "visible"
