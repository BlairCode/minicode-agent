from __future__ import annotations

import platform
from pathlib import Path

import pytest

from minicode_agent.app import Application
from minicode_agent.agent.state import AgentState
from minicode_agent.config import ConfigError
from minicode_agent.llm.client import ModelError
from minicode_agent.llm.types import ModelResponse, ToolCall

from conftest import ScriptedLLM


def test_runtime_feeds_tool_result_back_to_model(config, tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    model = ScriptedLLM(
        [
            ModelResponse(tool_calls=[ToolCall("write-1", "write_file", {"path": "hello.py", "content": "print('hi')\n"})]),
            ModelResponse(tool_calls=[ToolCall("read-1", "read_file", {"path": "hello.py"})]),
            ModelResponse(text="Created hello.py and verified its contents."),
        ]
    )
    config.storage.data_dir = str(tmp_path / "data")
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    runtime = app.create_runtime(
        "coding",
        interactive=False,
        record_sessions=False,
        event_handler=lambda event, payload: events.append((event, payload)),
    )
    run = runtime.run("Create hello.py and verify it")

    assert run.state is AgentState.COMPLETED
    assert run.steps == 3 and run.tool_calls == 2
    assert (app.workspace / "hello.py").exists()
    second_request = model.calls[1][0]
    assert any(message.get("role") == "tool" and "Created hello.py" in message["content"] for message in second_request)
    actions = [payload for event, payload in events if event == "model_action"]
    assert actions[0]["description"] == "编写 hello.py"
    assert actions[-1]["description"] == "整理执行结果并生成最终回答"


def test_runtime_stops_at_max_steps(config, tmp_path: Path) -> None:
    config.agent.max_steps = 2
    calls = [
        ModelResponse(tool_calls=[ToolCall(str(index), "list_directory", {"path": "."})])
        for index in range(3)
    ]
    config.storage.data_dir = str(tmp_path / "data")
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=ScriptedLLM(calls))
    run = app.create_runtime("coding", interactive=False, record_sessions=False).run("Keep inspecting")
    assert run.state is AgentState.MAX_STEPS
    assert run.steps == 2


def test_runtime_stops_at_tool_error_limit(config) -> None:
    config.agent.max_tool_errors = 2
    model = ScriptedLLM(
        [
            ModelResponse(tool_calls=[ToolCall("1", "missing", {})]),
            ModelResponse(tool_calls=[ToolCall("2", "missing", {})]),
        ]
    )
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    run = app.create_runtime("coding", interactive=False, record_sessions=False).run("Use a bad tool")
    assert run.state is AgentState.MAX_TOOL_ERRORS
    assert run.tool_errors == 2
    assert run.consecutive_tool_errors == 2


def test_successful_tool_call_resets_consecutive_error_limit(config) -> None:
    config.agent.max_tool_errors = 2
    model = ScriptedLLM(
        [
            ModelResponse(tool_calls=[ToolCall("1", "missing", {})]),
            ModelResponse(tool_calls=[ToolCall("2", "list_directory", {"path": "."})]),
            ModelResponse(tool_calls=[ToolCall("3", "missing", {})]),
            ModelResponse(text="Recovered after separate tool errors."),
        ]
    )
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)

    run = app.create_runtime("coding", interactive=False, record_sessions=False).run("Recover")

    assert run.state is AgentState.COMPLETED
    assert run.tool_errors == 2
    assert run.consecutive_tool_errors == 1


def test_cancellation_interrupts_model_retry_backoff(config) -> None:
    class FailingLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, _messages, _tools) -> ModelResponse:
            self.calls += 1
            raise ModelError("temporary provider failure")

    config.model.max_retries = 3
    config.agent.retry_base_seconds = 30
    model = FailingLLM()
    runtime_ref = {}

    def cancel_on_retry(event: str, _payload: dict) -> None:
        if event == "model_retry":
            runtime_ref["runtime"].cancel()

    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    runtime = app.create_runtime(
        "coding",
        interactive=False,
        record_sessions=False,
        event_handler=cancel_on_retry,
    )
    runtime_ref["runtime"] = runtime
    run = runtime.run("Trigger one retry, then cancel")

    assert run.state is AgentState.CANCELLED
    assert run.stop_reason == "cancelled by user"
    assert model.calls == 1


def test_both_agents_share_runtime_class(config) -> None:
    model = ScriptedLLM([ModelResponse(text="done"), ModelResponse(text="done")])
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    coding = app.create_runtime("coding", interactive=False, record_sessions=False)
    leetcode = app.create_runtime("leetcode", interactive=False, record_sessions=False)
    assert type(coding) is type(leetcode)
    assert coding.spec.name != leetcode.spec.name
    system_prompt = coding.context.messages[0]["content"]
    assert f"platform={platform.system()}" in system_prompt
    assert "shell=False" in system_prompt


def test_runtime_workspace_override_cannot_escape_base(config, tmp_path: Path) -> None:
    app = Application(
        config,
        project_root=Path(__file__).resolve().parents[1],
        llm=ScriptedLLM([ModelResponse(text="done")]),
    )
    with pytest.raises(ConfigError):
        app.create_runtime("coding", workspace=tmp_path / "outside")


def test_runtime_adds_private_workspace_context_without_changing_logged_task(config) -> None:
    events: list[tuple[str, dict]] = []
    model = ScriptedLLM([ModelResponse(text="done")])
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    runtime = app.create_runtime(
        "coding",
        interactive=False,
        record_sessions=False,
        event_handler=lambda event, payload: events.append((event, payload)),
    )

    runtime.run(
        "Implement the requested code",
        metadata={"workspace_initially_empty": True, "uploaded_files": ["requirements.txt"]},
    )

    user_message = next(message["content"] for message in model.calls[0][0] if message["role"] == "user")
    first_tool_names = {item["function"]["name"] for item in model.calls[0][1]}
    assert user_message.startswith("Implement the requested code")
    assert "do not call list_directory" in user_message
    assert "requirements.txt" in user_message
    assert "list_directory" not in first_tool_names
    started = next(payload for event, payload in events if event == "run_started")
    assert started["task"] == "Implement the requested code"
