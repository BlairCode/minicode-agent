from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from .command_policy import RiskLevel


class ApprovalManager:
    """Handles one-shot and exact-command approvals without fuzzy allow rules."""

    def __init__(
        self,
        *,
        interactive: bool = True,
        prompt: Callable[[str], str] | None = None,
        event_handler: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.interactive = interactive
        self.prompt = prompt or input
        self.event_handler = event_handler or (lambda _event, _payload: None)
        self._session_commands: set[str] = set()
        self._session_paths: set[str] = set()

    @staticmethod
    def _fingerprint(value: str) -> str:
        normalized = " ".join(value.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def request_command(self, command: str, risk: RiskLevel, reason: str) -> bool:
        fingerprint = self._fingerprint(command)
        if fingerprint in self._session_commands:
            return True
        if not self.interactive:
            return False
        self.event_handler("approval_requested", {"kind": "command", "command": command, "risk": risk.value, "reason": reason})
        message = (
            f"\nAgent requests:\n{command}\n\nRisk: {risk.value}\n"
            f"Reason: {reason}\n[y] Allow once  [a] Allow for session  [n] Deny\n> "
        )
        try:
            answer = self.prompt(message).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.event_handler("approval_resolved", {"kind": "command", "allowed": False})
            return False
        allowed = answer in {"a", "y"}
        self.event_handler("approval_resolved", {"kind": "command", "allowed": allowed})
        if answer == "a":
            self._session_commands.add(fingerprint)
            return True
        return answer == "y"

    def request_path(self, path: Path) -> bool:
        key = str(path)
        if key in self._session_paths:
            return True
        if not self.interactive:
            return False
        self.event_handler("approval_requested", {"kind": "path", "path": str(path)})
        try:
            answer = self.prompt(
                f"\nAgent requests access outside the workspace:\n{path}\n"
                "[y] Allow once  [a] Allow for session  [n] Deny\n> "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.event_handler("approval_resolved", {"kind": "path", "allowed": False})
            return False
        allowed = answer in {"a", "y"}
        self.event_handler("approval_resolved", {"kind": "path", "allowed": allowed})
        if answer == "a":
            self._session_paths.add(key)
            return True
        return answer == "y"
