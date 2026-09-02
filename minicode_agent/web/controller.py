from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import uuid4

from minicode_agent.agent.runtime import AgentRuntime
from minicode_agent.app import Application
from minicode_agent.config import AppConfig
from minicode_agent.personal import (
    CredentialStore,
    HistoryRepository,
    PersonalSettings,
    PersonalSettingsStore,
)
from minicode_agent.safety import PathPolicy
from minicode_agent.session import redact
from minicode_agent.tools.filesystem import WriteFileTool


MAX_UPLOAD_FILES = 10
MAX_UPLOAD_TOTAL_BYTES = 4_000_000


def open_directory(path: Path) -> None:
    """Open a local directory with the platform file manager."""
    if sys.platform == "win32":
        os.startfile(str(path))
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def public_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    visible = deepcopy(arguments)
    if "content" in visible:
        visible["content"] = f"<content: {len(str(visible['content']))} chars>"
    for key in ("old_text", "new_text"):
        if key in visible and len(str(visible[key])) > 180:
            visible[key] = str(visible[key])[:180] + "…"
    return visible


@dataclass(slots=True)
class PendingApproval:
    message: str
    run_id: str
    answer: str = "n"
    completed: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class WebRun:
    id: str
    task: str
    agent: str
    workspace: Path
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "IDLE"
    turn_count: int = 0
    runtime: AgentRuntime | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, event: str, payload: dict[str, Any]) -> None:
        if event == "tool_call":
            payload = {**payload, "arguments": public_tool_arguments(payload.get("arguments", {}))}
        payload = redact(payload)
        with self.lock:
            self.events.append({"seq": len(self.events), "event": event, "payload": payload})

    def snapshot(self, after: int) -> dict[str, Any]:
        with self.lock:
            events = [item for item in self.events if item["seq"] > after]
            next_after = self.events[-1]["seq"] if self.events else after
            return {"id": self.id, "status": self.status, "events": events, "next_after": next_after}


class WebController:
    """Thread-safe bridge between the local HTTP UI and AgentRuntime."""

    SETTINGS_FIELDS = {
        "provider",
        "model",
        "base_url",
        "request_timeout",
        "workspace",
        "command_mode",
        "network_access",
        "code_style",
        "comment_level",
        "default_language",
        "leetcode_language",
        "leetcode_mode",
    }

    def __init__(
        self,
        app: Application,
        config: AppConfig,
        project_root: Path,
        settings: PersonalSettings,
        settings_store: PersonalSettingsStore,
        credential_store: CredentialStore | None,
    ) -> None:
        self.app = app
        self.config = config
        self.project_root = project_root
        self.settings = settings
        self.settings_store = settings_store
        self.credential_store = credential_store
        self.history = HistoryRepository(app.data_dir)
        self.runs: dict[str, WebRun] = {}
        self.approvals: dict[str, PendingApproval] = {}
        self.lock = threading.RLock()

    def bootstrap(self) -> dict[str, Any]:
        return {
            "settings": self.public_settings(),
            "history": self.history.list_sessions(),
            "agents": ["coding", "leetcode"],
            "default_agent": self.config.agent.default,
        }

    def public_settings(self) -> dict[str, Any]:
        values = asdict(self.settings)
        stored_key = self.credential_store.get(self.settings.provider) if self.credential_store else None
        environment_key = os.getenv(self.config.model.api_key_env)
        values["has_api_key"] = bool(stored_key or environment_key)
        values["credential_source"] = "system" if stored_key else ("environment" if environment_key else "none")
        return values

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        updates = {key: value for key, value in payload.items() if key in self.SETTINGS_FIELDS}
        candidate = replace(self.settings, **updates)
        candidate.apply(self.config)
        api_key = payload.get("api_key")
        remove_key = payload.get("remove_api_key") is True
        if api_key:
            if not self.credential_store:
                raise RuntimeError("system credential storage is unavailable")
            self.credential_store.set(candidate.provider, str(api_key))
        elif remove_key and self.credential_store:
            self.credential_store.delete(candidate.provider)
        self.settings_store.save(candidate)
        self.settings = candidate
        self.app = Application(
            self.config,
            project_root=self.project_root,
            credential_provider=self._credential,
        )
        self.history = HistoryRepository(self.app.data_dir)
        return self.public_settings()

    def _credential(self) -> str | None:
        return self.credential_store.get(self.config.model.provider) if self.credential_store else None

    def _normalize_uploads(self, uploads: Any) -> list[dict[str, str]]:
        if uploads in (None, []):
            return []
        if not isinstance(uploads, list):
            raise ValueError("files must be a list")
        if len(uploads) > MAX_UPLOAD_FILES:
            raise ValueError(f"at most {MAX_UPLOAD_FILES} files can be uploaded at once")
        normalized: list[dict[str, str]] = []
        names: set[str] = set()
        total_bytes = 0
        for item in uploads:
            if not isinstance(item, dict):
                raise ValueError("each uploaded file must be an object")
            name = item.get("name")
            content = item.get("content")
            if not isinstance(name, str) or not name or name in {".", ".."}:
                raise ValueError("uploaded file name is invalid")
            if (
                "/" in name
                or "\\" in name
                or "\x00" in name
                or any(ord(char) < 32 for char in name)
                or name.endswith((" ", "."))
                or Path(name).name != name
                or PureWindowsPath(name).is_reserved()
            ):
                raise ValueError("uploaded files must use plain file names")
            if not isinstance(content, str):
                raise ValueError(f"uploaded file {name} must contain UTF-8 text")
            encoded_size = len(content.encode("utf-8"))
            if encoded_size > self.config.workspace.max_read_bytes:
                raise ValueError(f"uploaded file {name} exceeds the per-file size limit")
            total_bytes += encoded_size
            if total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                raise ValueError("uploaded files exceed the total size limit")
            canonical_name = name.casefold()
            if canonical_name in names:
                raise ValueError(f"duplicate uploaded file name: {name}")
            names.add(canonical_name)
            normalized.append({"name": name, "content": content})
        return normalized

    def _store_uploads(self, workspace: Path, uploads: list[dict[str, str]]) -> list[str]:
        if not uploads:
            return []
        policy = PathPolicy(workspace)
        targets = [policy.resolve(item["name"], must_exist=False, expect_directory=False) for item in uploads]
        for item, target in zip(uploads, targets, strict=True):
            if target.exists():
                raise ValueError(f"uploaded file already exists: {item['name']}")
        writer = WriteFileTool(policy, max_read_bytes=self.config.workspace.max_read_bytes)
        for item in uploads:
            result = writer.execute(item["name"], item["content"], overwrite=False)
            if not result.success:
                raise ValueError(result.error or f"could not store uploaded file {item['name']}")
        return [item["name"] for item in uploads]

    @staticmethod
    def _valid_conversation_id(value: str) -> bool:
        return len(value) == 32 and all(char in "0123456789abcdef" for char in value.lower())

    @staticmethod
    def _restore_context(runtime: AgentRuntime, events: list[dict[str, Any]]) -> int:
        turns = 0
        awaiting_response = False
        for item in events:
            event = item.get("event")
            payload = item.get("payload", {})
            if event == "run_started" and payload.get("task"):
                runtime.context.add_user(str(payload["task"]))
                turns += 1
                awaiting_response = True
            elif event == "final" and payload.get("text"):
                runtime.context.add_assistant(str(payload["text"]))
                awaiting_response = False
            elif event == "run_finished" and awaiting_response:
                reason = str(payload.get("reason", "previous attempt did not complete"))
                runtime.context.add_assistant(f"[Previous attempt ended without a final answer: {reason}]")
                awaiting_response = False
        return turns

    def _attach_runtime(self, conversation: WebRun, history: list[dict[str, Any]] | None = None) -> None:
        conversation_id = conversation.id

        def event_handler(event: str, payload: dict[str, Any]) -> None:
            conversation.add(event, payload)

        def approval_prompt(message: str) -> str:
            approval_id = uuid4().hex
            pending = PendingApproval(message, conversation_id)
            with self.lock:
                self.approvals[approval_id] = pending
            conversation.add("approval_prompt", {"id": approval_id, "message": message})
            pending.completed.wait()
            with self.lock:
                self.approvals.pop(approval_id, None)
            return pending.answer

        runtime = self.app.create_runtime(
            conversation.agent,
            workspace=conversation.workspace,
            interactive=True,
            approval_prompt=approval_prompt,
            event_handler=event_handler,
        )
        if history:
            conversation.turn_count = self._restore_context(runtime, history)
        conversation.runtime = runtime

    def _restore_conversation(self, conversation_id: str) -> WebRun:
        if not self._valid_conversation_id(conversation_id):
            raise KeyError("conversation not found")
        events = self.history.load(conversation_id)
        started = next((item for item in events if item.get("event") == "run_started"), None)
        if not started:
            raise KeyError("conversation not found")
        payload = started.get("payload", {})
        workspace_id = str(payload.get("workspace_id", conversation_id))
        workspace = self.app.workspace
        if self._valid_conversation_id(workspace_id):
            candidate = self.app.workspace / workspace_id
            if candidate.is_dir():
                workspace = candidate
        conversation = WebRun(
            conversation_id,
            str(payload.get("task", "Untitled task")),
            str(payload.get("agent", "coding")),
            workspace,
        )
        self._attach_runtime(conversation, events)
        with self.lock:
            self.runs[conversation_id] = conversation
        return conversation

    def start_run(
        self,
        task: str,
        agent: str,
        conversation_id: str = "",
        files: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task cannot be empty")
        if len(task) > 100_000:
            raise ValueError("task is too large")
        if agent not in {"coding", "leetcode"}:
            raise ValueError("unknown agent")
        uploads = self._normalize_uploads(files)
        if conversation_id:
            with self.lock:
                conversation = self.runs.get(conversation_id)
            conversation = conversation or self._restore_conversation(conversation_id)
            if conversation.agent != agent:
                raise ValueError("agent cannot change inside an existing conversation")
        else:
            conversation_id = uuid4().hex
            conversation_workspace = self.app.workspace / conversation_id
            conversation_workspace.mkdir(parents=True, exist_ok=False)
            conversation = WebRun(conversation_id, task.strip(), agent, conversation_workspace)
            self._attach_runtime(conversation)
            with self.lock:
                self.runs[conversation_id] = conversation

        with conversation.lock:
            if conversation.status == "RUNNING":
                raise ValueError("conversation is already running")
            workspace_initially_empty = not any(conversation.workspace.iterdir())
            uploaded_files = self._store_uploads(conversation.workspace, uploads)
            baseline = conversation.events[-1]["seq"] if conversation.events else -1
            conversation.status = "RUNNING"
            conversation.turn_count += 1
            turn_number = conversation.turn_count
        with self.lock:
            if len(self.runs) > 30:
                oldest = next(iter(self.runs))
                if oldest != conversation_id and self.runs[oldest].status != "RUNNING":
                    self.runs.pop(oldest, None)

        def work() -> None:
            try:
                result = conversation.runtime.run(
                    task,
                    session_id=conversation_id,
                    metadata={
                        "workspace_id": conversation_id,
                        "turn": turn_number,
                        "workspace_initially_empty": turn_number == 1 and workspace_initially_empty,
                        "uploaded_files": uploaded_files,
                    },
                )
                with conversation.lock:
                    conversation.status = result.state.value
                conversation.add(
                    "run_complete",
                    {
                        "state": result.state.value,
                        "response": result.final_response,
                        "reason": result.stop_reason,
                        "steps": result.steps,
                        "tool_calls": result.tool_calls,
                        "tool_errors": result.tool_errors,
                    },
                )
            except Exception as exc:
                with conversation.lock:
                    conversation.status = "FAILED"
                conversation.add("run_complete", {"state": "FAILED", "response": "", "reason": f"{type(exc).__name__}: {exc}"})

        threading.Thread(target=work, name=f"minicode-web-{conversation_id[:8]}", daemon=True).start()
        return {"id": conversation_id, "after": baseline, "turn": turn_number, "uploaded_files": uploaded_files}

    def run_events(self, run_id: str, after: int) -> dict[str, Any]:
        with self.lock:
            run = self.runs.get(run_id)
        if not run:
            raise KeyError("run not found")
        return run.snapshot(after)

    def cancel_run(self, run_id: str) -> None:
        with self.lock:
            run = self.runs.get(run_id)
        if not run or not run.runtime:
            raise KeyError("run not found")
        run.runtime.cancel()
        with self.lock:
            waiting = [item for item in self.approvals.values() if item.run_id == run_id]
        for pending in waiting:
            pending.answer = "n"
            pending.completed.set()

    def resolve_approval(self, approval_id: str, answer: str) -> None:
        if answer not in {"y", "a", "n"}:
            raise ValueError("invalid approval answer")
        with self.lock:
            pending = self.approvals.get(approval_id)
        if not pending:
            raise KeyError("approval not found")
        pending.answer = answer
        pending.completed.set()

    def history_events(self, session_id: str) -> list[dict[str, Any]]:
        events = self.history.load(session_id)
        safe: list[dict[str, Any]] = []
        for item in events:
            copy = deepcopy(item)
            if copy.get("event") == "tool_call":
                payload = copy.get("payload", {})
                payload["arguments"] = public_tool_arguments(payload.get("arguments", {}))
            safe.append(redact(copy))
        return safe

    def _workspace_policy(self, workspace_id: str = "") -> PathPolicy:
        workspace = self.app.workspace
        if workspace_id:
            with self.lock:
                active_run = self.runs.get(workspace_id)
            if active_run:
                workspace = active_run.workspace
            elif self._valid_conversation_id(workspace_id):
                historical_workspace = self.app.workspace / workspace_id
                if historical_workspace.is_dir():
                    workspace = historical_workspace
                else:
                    raise KeyError("conversation workspace not found")
            else:
                raise KeyError("conversation workspace not found")
        return PathPolicy(workspace)

    def preview_file(self, value: str, workspace_id: str = "") -> dict[str, Any]:
        policy = self._workspace_policy(workspace_id)
        path = policy.resolve(value, must_exist=True, expect_directory=False)
        if path.stat().st_size > 500_000:
            raise ValueError("file is too large to preview")
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            raise ValueError("binary files cannot be previewed")
        content = raw.decode("utf-8")
        return {"path": policy.display(path), "content": content}

    def open_file_location(self, value: str, workspace_id: str = "") -> dict[str, Any]:
        policy = self._workspace_policy(workspace_id)
        path = policy.resolve(value, must_exist=True, expect_directory=False)
        open_directory(path.parent)
        return {"opened": True, "path": policy.display(path)}
