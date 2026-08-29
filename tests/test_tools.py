from __future__ import annotations

import sys
from pathlib import Path

from minicode_agent.llm.types import ToolCall
from minicode_agent.safety import ApprovalManager, CommandPolicy, PathPolicy
from minicode_agent.tools.command import RunCommandTool
from minicode_agent.tools.dispatcher import ToolDispatcher
from minicode_agent.tools.filesystem import PatchFileTool, ReadFileTool, WriteFileTool
from minicode_agent.tools.registry import ToolRegistry


def test_file_write_read_and_patch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = PathPolicy(workspace)
    writer = WriteFileTool(policy)
    reader = ReadFileTool(policy)
    patcher = PatchFileTool(policy)

    assert writer.call({"path": "src/calc.py", "content": "answer = 41\n"}).success
    result = reader.call({"path": "src/calc.py"})
    assert result.success and result.output == "answer = 41\n"
    assert patcher.call(
        {"path": "src/calc.py", "old_text": "41", "new_text": "42", "count": 1}
    ).success
    assert (workspace / "src" / "calc.py").read_text(encoding="utf-8") == "answer = 42\n"


def test_dispatcher_reports_unknown_and_invalid_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry([ReadFileTool(PathPolicy(tmp_path))])
    dispatcher = ToolDispatcher(registry)
    unknown = dispatcher.dispatch(ToolCall("1", "missing", {}), frozenset({"missing"}))
    invalid = dispatcher.dispatch(ToolCall("2", "read_file", {}), frozenset({"read_file"}))
    assert not unknown.success and "unknown tool" in (unknown.error or "")
    assert not invalid.success and "missing required" in (invalid.error or "")


def test_command_timeout_returns_structured_result(tmp_path: Path) -> None:
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    tool = RunCommandTool(
        PathPolicy(tmp_path),
        CommandPolicy("strict"),
        ApprovalManager(interactive=False),
        timeout=0.1,
    )
    result = tool.call({"command": f'"{sys.executable}" slow.py'})
    assert not result.success
    assert result.data["timed_out"] is True
    assert "timed out" in (result.error or "")


def test_tool_argument_type_error_does_not_raise(tmp_path: Path) -> None:
    result = ReadFileTool(PathPolicy(tmp_path)).call({"path": 123})
    assert not result.success
    assert "must be string" in (result.error or "")


def test_write_size_limit_is_enforced(tmp_path: Path) -> None:
    result = WriteFileTool(PathPolicy(tmp_path), max_read_bytes=4).call(
        {"path": "large.txt", "content": "12345"}
    )
    assert not result.success
    assert not (tmp_path / "large.txt").exists()
