from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


@dataclass(slots=True)
class ToolResult:
    success: bool
    output: str = ""
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    fatal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        properties = self.parameters.get("properties", {})
        required = set(self.parameters.get("required", []))
        missing = sorted(required - set(arguments))
        if missing:
            return f"missing required arguments: {', '.join(missing)}"
        if self.parameters.get("additionalProperties") is False:
            unknown = sorted(set(arguments) - set(properties))
            if unknown:
                return f"unknown arguments: {', '.join(unknown)}"
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in arguments.items():
            rules = properties.get(key, {})
            expected = rules.get("type")
            if expected in type_map:
                expected_type = type_map[expected]
                if expected in {"integer", "number"} and isinstance(value, bool):
                    return f"argument '{key}' must be {expected}"
                if not isinstance(value, expected_type):
                    return f"argument '{key}' must be {expected}"
            if "enum" in rules and value not in rules["enum"]:
                return f"argument '{key}' must be one of: {', '.join(map(str, rules['enum']))}"
            if expected in {"integer", "number"}:
                if "minimum" in rules and value < rules["minimum"]:
                    return f"argument '{key}' must be at least {rules['minimum']}"
                if "maximum" in rules and value > rules["maximum"]:
                    return f"argument '{key}' must be at most {rules['maximum']}"
            if expected == "string":
                if "minLength" in rules and len(value) < rules["minLength"]:
                    return f"argument '{key}' is too short"
                if "maxLength" in rules and len(value) > rules["maxLength"]:
                    return f"argument '{key}' is too long"
        return None

    def call(self, arguments: dict[str, Any]) -> ToolResult:
        validation_error = self.validate_arguments(arguments)
        if validation_error:
            return ToolResult(False, error=validation_error)
        started = time.perf_counter()
        try:
            result = self.execute(**arguments)
        except Exception as exc:
            result = ToolResult(False, error=f"{type(exc).__name__}: {exc}")
        result.metadata.setdefault("duration_ms", round((time.perf_counter() - started) * 1000))
        return result

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
