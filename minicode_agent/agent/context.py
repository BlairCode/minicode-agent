from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from minicode_agent.llm.types import ToolCall
from minicode_agent.tools.base import ToolResult


class ContextManager:
    """Stores provider-neutral messages and performs deterministic trimming."""

    def __init__(
        self,
        base_prompt: str,
        agent_prompt: str,
        skill_text: str,
        *,
        char_budget: int = 100_000,
        max_tool_result_chars: int = 20_000,
    ) -> None:
        self.char_budget = char_budget
        self.max_tool_result_chars = max_tool_result_chars
        combined = "\n\n".join(part.strip() for part in (base_prompt, agent_prompt, skill_text) if part.strip())
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": combined}]
        self.current_task_index: int | None = None
        self.trimmed_messages = 0

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self.current_task_index = len(self.messages) - 1

    def add_assistant_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        tool_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments or {}, ensure_ascii=False),
                },
            }
            for call in calls
        ]
        self.messages.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})

    def add_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        payload = result.to_dict()
        content = json.dumps(payload, ensure_ascii=False, default=str)
        if len(content) > self.max_tool_result_chars:
            limit = max(100, self.max_tool_result_chars // 4)
            payload["output"] = str(payload.get("output", ""))[:limit] + "... [truncated]"
            data = payload.get("data", {})
            if isinstance(data, dict):
                for key in ("stdout", "stderr"):
                    if key in data:
                        data[key] = str(data[key])[:limit] + "... [truncated]"
                data["truncated_by_context"] = True
            content = json.dumps(payload, ensure_ascii=False, default=str)
            if len(content) > self.max_tool_result_chars:
                payload["data"] = {"truncated_by_context": True}
                payload["output"] = str(payload["output"])[: max(80, self.max_tool_result_chars // 2)]
                content = json.dumps(payload, ensure_ascii=False, default=str)
        self.messages.append(
            {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": content}
        )

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def clear_history(self) -> None:
        self.messages = self.messages[:1]
        self.current_task_index = None
        self.trimmed_messages = 0

    @staticmethod
    def _size(message: dict[str, Any]) -> int:
        return len(json.dumps(message, ensure_ascii=False, default=str))

    @staticmethod
    def _group(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        groups: list[list[dict[str, Any]]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                group = [message]
                index += 1
                while index < len(messages) and messages[index].get("role") == "tool":
                    group.append(messages[index])
                    index += 1
                groups.append(group)
            else:
                groups.append([message])
                index += 1
        return groups

    def build(self) -> list[dict[str, Any]]:
        if sum(self._size(item) for item in self.messages) <= self.char_budget:
            return deepcopy(self.messages)
        system = deepcopy(self.messages[0])
        task = (
            deepcopy(self.messages[self.current_task_index])
            if self.current_task_index is not None
            else None
        )
        reserved = self._size(system) + (self._size(task) if task else 0) + 160
        split_at = self.current_task_index or 1
        before_groups = self._group(self.messages[1:split_at])
        after_groups = self._group(self.messages[split_at + 1 :])
        used = reserved
        selected_after: list[list[dict[str, Any]]] = []
        for group in reversed(after_groups):
            group_size = sum(self._size(item) for item in group)
            if used + group_size <= self.char_budget:
                selected_after.append(deepcopy(group))
                used += group_size
        selected_after.reverse()
        selected_before: list[list[dict[str, Any]]] = []
        for group in reversed(before_groups):
            group_size = sum(self._size(item) for item in group)
            if used + group_size <= self.char_budget:
                selected_before.append(deepcopy(group))
                used += group_size
        selected_before.reverse()
        kept_count = 1 + (1 if task else 0) + sum(
            len(group) for group in selected_before + selected_after
        )
        self.trimmed_messages = max(0, len(self.messages) - kept_count)
        marker = {
            "role": "system",
            "content": f"[Context trimmed: {self.trimmed_messages} older message(s) omitted.]",
        }
        result = [system, marker]
        for group in selected_before:
            result.extend(group)
        if task:
            result.append(task)
        for group in selected_after:
            result.extend(group)
        return result
