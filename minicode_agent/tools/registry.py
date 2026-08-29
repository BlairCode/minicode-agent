from __future__ import annotations

from collections.abc import Iterable

from .base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"tool name is empty or already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def schemas(self, enabled: set[str] | frozenset[str]) -> list[dict]:
        return [self._tools[name].schema() for name in sorted(enabled) if name in self._tools]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

