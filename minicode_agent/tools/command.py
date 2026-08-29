from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from minicode_agent.safety.approval import ApprovalManager
from minicode_agent.safety.command_policy import CommandPolicy
from minicode_agent.safety.path_policy import PathPolicy

from .base import BaseTool, ToolResult


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    half = max(1, (limit - 80) // 2)
    return value[:half] + "\n... [output truncated] ...\n" + value[-half:], True


def _sanitized_environment() -> dict[str, str]:
    sensitive = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in sensitive)
    }


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Run one local development command without a shell and return structured output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Single command; shell operators are rejected"},
            "cwd": {"type": "string", "default": "."},
            "timeout": {"type": "number", "minimum": 0.1},
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        path_policy: PathPolicy,
        command_policy: CommandPolicy,
        approval_manager: ApprovalManager,
        *,
        timeout: float = 30.0,
        max_output_chars: int = 20_000,
    ) -> None:
        self.path_policy = path_policy
        self.command_policy = command_policy
        self.approval_manager = approval_manager
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def execute(self, command: str, cwd: str = ".", timeout: float | None = None) -> ToolResult:
        decision = self.command_policy.evaluate(command)
        base_data = {"risk": decision.risk.value, "reason": decision.reason}
        if not decision.allowed:
            return ToolResult(False, error=f"command denied: {decision.reason}", data=base_data)
        if decision.approval_required and not self.approval_manager.request_command(
            command, decision.risk, decision.reason
        ):
            return ToolResult(False, error="command approval denied", data=base_data)
        working_directory = self.path_policy.resolve(cwd, must_exist=True, expect_directory=True)
        effective_timeout = min(float(timeout or self.timeout), self.timeout)
        if effective_timeout <= 0:
            return ToolResult(False, error="timeout must be positive", data=base_data)

        started = time.perf_counter()
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                list(decision.argv),
                cwd=working_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=_sanitized_environment(),
                start_new_session=os.name != "nt",
                creationflags=creation_flags,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(False, error=f"cannot start command: {exc}", data=base_data)

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_tree(process)
            stdout, stderr = process.communicate()
        duration_ms = round((time.perf_counter() - started) * 1000)
        stdout, stdout_truncated = _truncate(stdout, self.max_output_chars)
        stderr, stderr_truncated = _truncate(stderr, self.max_output_chars)
        data = {
            **base_data,
            "command": command,
            "cwd": self.path_policy.display(working_directory),
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
            "output_truncated": stdout_truncated or stderr_truncated,
        }
        success = process.returncode == 0 and not timed_out
        if timed_out:
            error = f"command timed out after {effective_timeout:g}s"
        elif process.returncode != 0:
            error = f"command exited with code {process.returncode}"
        else:
            error = None
        summary_parts = [f"exit_code={process.returncode}", f"duration_ms={duration_ms}"]
        if stdout:
            summary_parts.append(f"stdout:\n{stdout}")
        if stderr:
            summary_parts.append(f"stderr:\n{stderr}")
        return ToolResult(success, output="\n".join(summary_parts), error=error, data=data)

