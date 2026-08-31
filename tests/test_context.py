from minicode_agent.agent.context import ContextManager
from minicode_agent.llm.types import ToolCall
import json

from minicode_agent.tools.base import ToolResult


def test_context_trimming_keeps_task_and_tool_call_pair() -> None:
    context = ContextManager("system", "agent", "skill", char_budget=4000, max_tool_result_chars=1000)
    for index in range(10):
        context.add_user("old task " + str(index) + " x" * 100)
        call = ToolCall(f"old-{index}", "read_file", {"path": "x"})
        context.add_assistant_tool_calls("", [call])
        context.add_tool_result(call, ToolResult(True, output="y" * 400))
    context.add_user("CURRENT TASK")
    call = ToolCall("new", "read_file", {"path": "current.py"})
    context.add_assistant_tool_calls("", [call])
    context.add_tool_result(call, ToolResult(True, output="current result"))
    built = context.build()
    assert any(item.get("content") == "CURRENT TASK" for item in built)
    assistant_index = next(i for i, item in enumerate(built) if item.get("tool_calls", [{}])[0].get("id") == "new")
    assert built[assistant_index + 1]["role"] == "tool"
    assert context.trimmed_messages > 0


def test_truncated_tool_result_remains_valid_json() -> None:
    context = ContextManager("system", "agent", "", char_budget=4000, max_tool_result_chars=500)
    context.add_user("task")
    call = ToolCall("large", "run_command", {"command": "pytest"})
    context.add_assistant_tool_calls("", [call])
    context.add_tool_result(
        call,
        ToolResult(
            True,
            output="OUTPUT_HEAD" + "x" * 5000 + "OUTPUT_TAIL",
            data={"stdout": "STDOUT_HEAD" + "y" * 5000 + "STDOUT_TAIL", "stderr": ""},
        ),
    )
    payload = json.loads(context.messages[-1]["content"])
    assert payload["success"] is True
    assert payload["data"]["truncated_by_context"] is True
    assert payload["output"].startswith("OUTPUT_HEAD")
    assert payload["output"].endswith("OUTPUT_TAIL")
    assert payload["data"]["stdout"].startswith("STDOUT_HEAD")
    assert payload["data"]["stdout"].endswith("STDOUT_TAIL")
