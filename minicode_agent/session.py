from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE),
)
SENSITIVE_KEYS = ("key", "token", "secret", "password", "passwd", "credential")


def redact(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


class SessionRecorder:
    """Append-only JSONL event recorder with recursive secret redaction."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path: Path | None = None
        self._lock = Lock()
        self.last_error: str | None = None

    def start(self, session_id: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path = self.root / f"{session_id}.jsonl"
        except OSError as exc:
            self.path = None
            self.last_error = f"{type(exc).__name__}: {exc}"

    def record(self, event: str, payload: dict[str, Any]) -> None:
        if self.path is None:
            return
        item = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "payload": redact(payload),
        }
        line = json.dumps(item, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(line)
                    stream.flush()
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.path = None
