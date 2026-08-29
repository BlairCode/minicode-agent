from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class AgentSpec:
    name: str
    description: str
    system_prompt: str
    enabled_tools: frozenset[str]
    enabled_skills: tuple[str, ...]

