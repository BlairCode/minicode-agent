from __future__ import annotations

import os
import platform
from collections.abc import Callable
from pathlib import Path

from minicode_agent.agent.context import ContextManager
from minicode_agent.agent.manager import AgentManager
from minicode_agent.agent.runtime import AgentRuntime
from minicode_agent.agent.stop import StopPolicy
from minicode_agent.config import AppConfig, ConfigError
from minicode_agent.llm import LLMClient, OpenAICompatibleClient, QwenClient
from minicode_agent.personal import user_data_directory
from minicode_agent.safety import ApprovalManager, CommandPolicy, PathPolicy
from minicode_agent.session import SessionRecorder
from minicode_agent.skills import SkillLoader
from minicode_agent.tools.command import RunCommandTool
from minicode_agent.tools.dispatcher import ToolDispatcher
from minicode_agent.tools.filesystem import (
    ListDirectoryTool,
    PatchFileTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from minicode_agent.tools.registry import ToolRegistry


def _runtime_environment_prompt() -> str:
    platform_name = platform.system() or os.name
    if os.name == "nt":
        command_guidance = (
            "Use Windows-compatible executables; do not use POSIX-only commands such as rm. "
            "Workspace-built .exe files may be invoked by relative path."
        )
    else:
        command_guidance = "Use POSIX-compatible executables and paths."
    return (
        f"Runtime environment: platform={platform_name}, os.name={os.name}. "
        "Commands are parsed into argv and executed with shell=False, so shell built-ins, "
        f"operators, redirection, and command chaining are unavailable. {command_guidance}"
    )


class Application:
    def __init__(
        self,
        config: AppConfig,
        *,
        project_root: str | Path = ".",
        llm: LLMClient | None = None,
        credential_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.workspace = self._resolve_workspace(config.workspace.root)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.data_dir = user_data_directory(config.storage.data_dir)
        try:
            self.data_dir.relative_to(self.project_root)
        except ValueError:
            pass
        else:
            raise ConfigError("storage.data_dir must be outside the project repository")
        self.credential_provider = credential_provider
        self.llm = llm or self._build_llm()
        self.agent_manager = AgentManager(
            self.project_root / "prompts",
            config.leetcode,
            config.coding,
        )
        self.skill_loader = SkillLoader(self.project_root / "skills")

    def _resolve_workspace(self, value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()

    def _build_llm(self) -> LLMClient:
        if self.config.model.provider == "qwen":
            return QwenClient(self.config.model, self.credential_provider)
        return OpenAICompatibleClient(self.config.model, self.credential_provider)

    def set_workspace(self, value: str) -> None:
        self.workspace = self._resolve_workspace(value)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def create_runtime(
        self,
        agent_name: str,
        *,
        workspace: str | Path | None = None,
        interactive: bool = True,
        approval_prompt: Callable[[str], str] | None = None,
        event_handler: Callable[[str, dict], None] | None = None,
        record_sessions: bool = True,
    ) -> AgentRuntime:
        spec = self.agent_manager.get(agent_name)
        runtime_workspace = self.workspace
        if workspace is not None:
            runtime_workspace = Path(workspace).resolve()
            try:
                runtime_workspace.relative_to(self.workspace)
            except ValueError as exc:
                raise ConfigError("runtime workspace must be inside the configured workspace") from exc
            runtime_workspace.mkdir(parents=True, exist_ok=True)
        runtime_ref: dict[str, AgentRuntime] = {}

        def route_event(event: str, payload: dict) -> None:
            runtime = runtime_ref.get("runtime")
            if runtime is not None:
                runtime.handle_external_event(event, payload)
            elif event_handler:
                event_handler(event, payload)

        approval = ApprovalManager(
            interactive=interactive,
            prompt=approval_prompt,
            event_handler=route_event,
        )
        path_policy = PathPolicy(
            runtime_workspace,
            allow_outside_workspace=self.config.workspace.allow_outside_workspace,
            outside_approval=approval.request_path,
        )
        command_policy = CommandPolicy(
            self.config.security.command_mode,
            network_access=self.config.security.network_access,
        )
        filesystem_options = {
            "max_read_bytes": self.config.workspace.max_read_bytes,
            "max_output_chars": self.config.workspace.max_tool_output_chars,
            "backup_before_overwrite": self.config.workspace.backup_before_overwrite,
        }
        tools = [
            ReadFileTool(path_policy, **filesystem_options),
            WriteFileTool(path_policy, **filesystem_options),
            PatchFileTool(path_policy, **filesystem_options),
            ListDirectoryTool(path_policy, **filesystem_options),
            SearchFilesTool(path_policy, **filesystem_options),
            RunCommandTool(
                path_policy,
                command_policy,
                approval,
                timeout=self.config.security.command_timeout,
                max_output_chars=self.config.workspace.max_tool_output_chars,
            ),
        ]
        registry = ToolRegistry(tools)
        dispatcher = ToolDispatcher(registry, route_event)
        base_prompt = (self.project_root / "prompts" / "base.md").read_text(encoding="utf-8")
        base_prompt += "\n\n" + _runtime_environment_prompt()
        context = ContextManager(
            base_prompt,
            spec.system_prompt,
            self.skill_loader.load(spec.enabled_skills),
            char_budget=self.config.agent.context_char_budget,
            max_tool_result_chars=self.config.workspace.max_tool_output_chars,
        )
        should_record = record_sessions and self.config.storage.keep_history
        recorder = SessionRecorder(self.data_dir / "sessions") if should_record else None
        runtime = AgentRuntime(
            self.llm,
            registry,
            dispatcher,
            context,
            StopPolicy(self.config.agent.max_steps, self.config.agent.max_tool_errors),
            spec,
            model_retries=self.config.model.max_retries,
            retry_base_seconds=self.config.agent.retry_base_seconds,
            recorder=recorder,
            event_handler=event_handler,
        )
        runtime_ref["runtime"] = runtime
        return runtime
