from __future__ import annotations

from pathlib import Path

import pytest

from minicode_agent.app import Application
from minicode_agent.agent.state import AgentState
from minicode_agent.config import ConfigError
from minicode_agent.llm.types import ModelResponse, ToolCall

from conftest import ScriptedLLM


def test_runtime_feeds_tool_result_back_to_model(config, tmp_path: Path) -> None:
    model = ScriptedLLM(
        [
            ModelResponse(tool_calls=[ToolCall("write-1", "write_file", {"path": "hello.py", "content": "print('hi')\n"})]),
            ModelResponse(tool_calls=[ToolCall("read-1", "read_file", {"path": "hello.py"})]),
            ModelResponse(text="Created hello.py and verified its contents."),
        ]
    )
    config.storage.data_dir = str(tmp_path / "data")
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    runtime = app.create_runtime("coding", interactive=False, record_sessions=False)
    run = runtime.run("Create hello.py and verify it")

    assert run.state is AgentState.COMPLETED
    assert run.steps == 3 and run.tool_calls == 2
    assert (app.workspace / "hello.py").exists()
    second_request = model.calls[1][0]
    assert any(message.get("role") == "tool" and "Created hello.py" in message["content"] for message in second_request)


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


def test_both_agents_share_runtime_class(config) -> None:
    model = ScriptedLLM([ModelResponse(text="done"), ModelResponse(text="done")])
    app = Application(config, project_root=Path(__file__).resolve().parents[1], llm=model)
    coding = app.create_runtime("coding", interactive=False, record_sessions=False)
    leetcode = app.create_runtime("leetcode", interactive=False, record_sessions=False)
    assert type(coding) is type(leetcode)
    assert coding.spec.name != leetcode.spec.name


def test_runtime_workspace_override_cannot_escape_base(config, tmp_path: Path) -> None:
    app = Application(
        config,
        project_root=Path(__file__).resolve().parents[1],
        llm=ScriptedLLM([ModelResponse(text="done")]),
    )
    with pytest.raises(ConfigError):
        app.create_runtime("coding", workspace=tmp_path / "outside")
