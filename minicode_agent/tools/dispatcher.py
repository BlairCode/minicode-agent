from __future__ import annotations

from collections.abc import Callable

from minicode_agent.llm.types import ToolCall

from .base import ToolResult
from .registry import ToolRegistry


class ToolDispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        event_handler: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.registry = registry
        self.event_handler = event_handler or (lambda _event, _payload: None)

    def dispatch(self, call: ToolCall, enabled: set[str] | frozenset[str]) -> ToolResult:
        if call.parse_error or call.arguments is None:
            return ToolResult(False, error=f"invalid tool arguments: {call.parse_error or 'not an object'}")
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolResult(False, error=f"unknown tool: {call.name}")
        if call.name not in enabled:
            return ToolResult(False, error=f"tool is not enabled for this agent: {call.name}")
        self.event_handler("tool_call", {"name": call.name, "arguments": call.arguments})
        result = tool.call(call.arguments)
        self.event_handler("tool_result", {"name": call.name, "result": result.to_dict()})
        return result

