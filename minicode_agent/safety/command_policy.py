from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


@dataclass(slots=True, frozen=True)
class CommandDecision:
    risk: RiskLevel
    allowed: bool
    approval_required: bool
    reason: str
    argv: tuple[str, ...] = ()


class CommandPolicy:
    SHELL_CONTROL = re.compile(r"[|&;<>`\r\n]|\$\(")
    BLOCKED_EXECUTABLES = {
        "shutdown",
        "reboot",
        "poweroff",
        "halt",
        "format",
        "mkfs",
        "diskpart",
    }
    SAFE_EXECUTABLES = {
        "python",
        "python3",
        "py",
        "pytest",
        "ruff",
        "mypy",
        "gcc",
        "g++",
        "clang",
        "clang++",
        "javac",
        "java",
        "node",
        "npm",
        "pnpm",
        "yarn",
        "bun",
        "tsc",
        "cargo",
        "go",
        "git",
        "ls",
        "dir",
        "pwd",
        "Get-ChildItem".lower(),
    }
    NETWORK_EXECUTABLES = {"curl", "wget", "ssh", "scp", "ftp", "Invoke-WebRequest".lower()}

    def __init__(self, mode: str = "ask", *, network_access: bool = False) -> None:
        if mode not in {"strict", "ask", "full"}:
            raise ValueError("command mode must be strict, ask, or full")
        self.mode = mode
        self.network_access = network_access

    def parse(self, command: str) -> tuple[str, ...]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        if self.SHELL_CONTROL.search(command):
            raise ValueError("shell control operators and redirection are not allowed")
        try:
            argv = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            raise ValueError(f"invalid command quoting: {exc}") from exc
        if os.name == "nt":
            argv = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in argv]
        if not argv:
            raise ValueError("command is empty")
        return tuple(argv)

    def evaluate(self, command: str) -> CommandDecision:
        try:
            argv = self.parse(command)
        except ValueError as exc:
            return CommandDecision(RiskLevel.BLOCKED, False, False, str(exc))

        executable = os.path.basename(argv[0]).lower()
        for suffix in (".exe", ".cmd", ".bat", ".com"):
            if executable.endswith(suffix):
                executable = executable[: -len(suffix)]
                break
        lowered = [part.lower() for part in argv]
        joined = " ".join(lowered)

        if executable in self.BLOCKED_EXECUTABLES:
            risk, reason = RiskLevel.BLOCKED, "system-level destructive command"
        elif self._is_catastrophic_delete(executable, lowered):
            risk, reason = RiskLevel.BLOCKED, "command may destroy a root or system directory"
        elif executable in self.NETWORK_EXECUTABLES and not self.network_access:
            risk, reason = RiskLevel.BLOCKED, "network access is disabled"
        elif self._is_high_risk(executable, lowered, joined):
            risk, reason = RiskLevel.HIGH, "destructive or difficult-to-recover operation"
        elif self._is_medium_risk(executable, lowered):
            risk, reason = RiskLevel.MEDIUM, "changes dependencies, repository state, or external resources"
        elif self._is_safe(executable, lowered):
            risk, reason = RiskLevel.SAFE, "recognized local development command"
        else:
            risk, reason = RiskLevel.MEDIUM, "unrecognized command requires review"

        if risk is RiskLevel.BLOCKED:
            return CommandDecision(risk, False, False, reason, argv)
        if risk is RiskLevel.HIGH:
            return CommandDecision(risk, True, True, reason, argv)
        if self.mode == "strict":
            return CommandDecision(risk, risk is RiskLevel.SAFE, False, reason, argv)
        if self.mode == "ask" and risk is RiskLevel.MEDIUM:
            return CommandDecision(risk, True, True, reason, argv)
        return CommandDecision(risk, True, False, reason, argv)

    @staticmethod
    def _is_catastrophic_delete(executable: str, args: list[str]) -> bool:
        roots = {"/", "\\", "c:\\", "c:/", "*", "."}
        if executable in {"rm", "rmdir", "del", "erase", "remove-item"}:
            return any(arg in roots for arg in args[1:]) and any(
                flag in args for flag in {"-r", "-rf", "-fr", "/s", "-recurse"}
            )
        return False

    @staticmethod
    def _is_high_risk(executable: str, args: list[str], joined: str) -> bool:
        if executable == "git":
            return (
                "reset --hard" in joined
                or " clean " in f" {joined} "
                or "--force" in args
                or "-f" in args and "push" in args
            )
        if executable in {"rm", "rmdir", "del", "erase", "remove-item"}:
            return True
        return executable in {"chmod", "chown", "takeown", "icacls"} and any(
            flag in args for flag in {"-r", "-recurse", "/t"}
        )

    @staticmethod
    def _is_medium_risk(executable: str, args: list[str]) -> bool:
        if executable in {"pip", "pip3", "uv", "npm", "pnpm", "yarn", "bun", "cargo"}:
            return any(action in args[1:] for action in {"install", "add", "remove", "uninstall", "update"})
        if executable in {"python", "python3", "py"}:
            return len(args) > 2 and args[1:3] in (["-m", "pip"], ["-m", "ensurepip"])
        if executable == "go":
            return len(args) > 1 and args[1] in {"get", "install"}
        if executable == "git":
            return len(args) > 1 and args[1] in {"checkout", "switch", "branch", "commit", "merge", "rebase", "pull", "push"}
        return executable in CommandPolicy.NETWORK_EXECUTABLES

    @staticmethod
    def _is_safe(executable: str, args: list[str]) -> bool:
        if executable not in CommandPolicy.SAFE_EXECUTABLES:
            return False
        if executable == "git":
            return len(args) > 1 and args[1] in {"status", "diff", "log", "show", "rev-parse"}
        if executable in {"npm", "pnpm", "yarn", "bun"}:
            return len(args) > 1 and args[1] in {"test", "run", "exec"}
        return True
