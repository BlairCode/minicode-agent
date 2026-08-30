from minicode_agent.agent.explanation import describe_tool_call, describe_tool_calls
from minicode_agent.llm.types import ToolCall


def test_file_tool_descriptions_include_the_target() -> None:
    assert (
        describe_tool_call(ToolCall("1", "read_file", {"path": "src/app.py"}))
        == "读取 src/app.py，了解相关实现"
    )
    assert (
        describe_tool_call(ToolCall("2", "patch_file", {"path": "src/app.py"}))
        == "修改 src/app.py 中的目标代码"
    )


def test_command_descriptions_explain_the_intent_without_echoing_arguments() -> None:
    description = describe_tool_call(
        ToolCall(
            "1",
            "run_command",
            {"command": "python -m pytest tests/test_api.py -q --token private-value"},
        )
    )
    assert description == "运行自动化测试并检查结果"
    assert "private-value" not in description


def test_multiple_tool_descriptions_stay_brief() -> None:
    description = describe_tool_calls(
        [
            ToolCall("1", "write_file", {"path": "solution.cpp", "content": "..."}),
            ToolCall("2", "run_command", {"command": "g++ solution.cpp -o solution.exe"}),
        ]
    )
    assert description == "编写 solution.cpp；编译源码并检查构建错误"


def test_windows_executable_suffix_does_not_hide_command_intent() -> None:
    compiler = ToolCall("1", "run_command", {"command": "g++.exe main.cpp -o main.exe"})
    tests = ToolCall("2", "run_command", {"command": "npm.exe test"})
    assert describe_tool_call(compiler) == "编译源码并检查构建错误"
    assert describe_tool_call(tests) == "运行自动化测试并检查结果"
