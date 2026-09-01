from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


class AgentState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MAX_STEPS = "MAX_STEPS"
    MAX_TOOL_ERRORS = "MAX_TOOL_ERRORS"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class AgentRun:
    task: str
    state: AgentState = AgentState.IDLE
    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    consecutive_tool_errors: int = 0
    final_response: str = ""
    stop_reason: str = ""
    session_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def finished(self) -> bool:
        return self.state in {
            AgentState.COMPLETED,
            AgentState.FAILED,
            AgentState.MAX_STEPS,
            AgentState.MAX_TOOL_ERRORS,
            AgentState.CANCELLED,
        }
