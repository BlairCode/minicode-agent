from __future__ import annotations

import re
from typing import Any

from minicode_agent.llm.types import ToolCall


def _short(value: Any, limit: int = 64) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "当前工作区"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _program_name(command: str) -> str:
    match = re.match(r"\s*(?:\"([^\"]+)\"|'([^']+)'|(\S+))", command)
    value = next((item for item in (match.groups() if match else ()) if item), "")
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _describe_command(command: str) -> str:
    normalized = " ".join(command.split())
    lowered = normalized.lower()
    program = _program_name(normalized)
    program = program[:-4] if program.endswith(".exe") else program

    if (
        "pytest" in lowered
        or "unittest" in lowered
        or "ctest" in lowered
        or program in {"npm", "pnpm", "yarn", "cargo", "go", "dotnet"}
        and re.search(r"\btest\b", lowered)
    ):
        return "运行自动化测试并检查结果"
    if "compileall" in lowered:
        return "检查 Python 代码语法"
    if program == "node" and "--check" in lowered:
        return "检查 JavaScript 代码语法"
    if program in {"g++", "gcc", "clang", "clang++", "cl"}:
        if "--version" in lowered:
            return f"检查 {program} 编译器是否可用"
        return "编译源码并检查构建错误"
    if (
        program in {"javac", "cargo", "cmake", "make", "msbuild", "dotnet"}
        or " npm run build" in f" {lowered}"
    ):
        return "构建项目并检查编译结果"
    if program == "git":
        if re.search(r"\bgit\s+status\b", lowered):
            return "检查 Git 工作区状态"
        if re.search(r"\bgit\s+diff\b", lowered):
            return "检查当前代码改动"
        if re.search(r"\bgit\s+log\b", lowered):
            return "查看 Git 提交历史"
        return "执行 Git 仓库检查"
    if program in {"rg", "grep", "findstr"}:
        return "搜索代码并定位相关实现"
    if program in {"ls", "dir", "tree", "get-childitem"}:
        return "查看工作区文件结构"
    if "pip install" in lowered or (
        program in {"npm", "pnpm", "yarn"} and "install" in lowered
    ):
        return "安装项目依赖"
    if "--version" in lowered:
        return f"检查 {_short(program, 24)} 是否可用"
    if _program_name(normalized).endswith((".exe", ".out")) or normalized.startswith(("./", ".\\")):
        return "运行生成的程序并检查输出"
    if program in {"python", "python3", "py"}:
        return "运行 Python 程序并检查输出"
    if program == "node":
        return "运行 JavaScript 程序并检查输出"
    return f"执行本地开发命令并检查结果（{_short(program or 'command', 24)}）"


def describe_tool_call(call: ToolCall) -> str:
    arguments = call.arguments or {}
    path = _short(arguments.get("path", "."))
    descriptions = {
        "read_file": f"读取 {path}，了解相关实现",
        "write_file": f"编写 {path}",
        "patch_file": f"修改 {path} 中的目标代码",
        "list_directory": f"查看 {path} 的文件结构",
        "search_files": f"在 {path} 中搜索相关代码",
    }
    if call.name == "run_command":
        return _describe_command(str(arguments.get("command", "")))
    return descriptions.get(call.name, f"调用 {call.name} 完成当前操作")


def describe_tool_calls(calls: list[ToolCall]) -> str:
    descriptions = [describe_tool_call(call) for call in calls]
    return "；".join(descriptions)
