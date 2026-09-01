from __future__ import annotations

from threading import Event

from .state import AgentRun, AgentState


class StopPolicy:
    def __init__(self, max_steps: int, max_tool_errors: int) -> None:
        self.max_steps = max_steps
        self.max_tool_errors = max_tool_errors

    def apply_limits(self, run: AgentRun, cancel_event: Event) -> bool:
        if cancel_event.is_set():
            run.state = AgentState.CANCELLED
            run.stop_reason = "cancelled by user"
            return True
        if run.consecutive_tool_errors >= self.max_tool_errors:
            run.state = AgentState.MAX_TOOL_ERRORS
            run.stop_reason = f"maximum consecutive tool errors reached ({self.max_tool_errors})"
            return True
        if run.steps >= self.max_steps:
            run.state = AgentState.MAX_STEPS
            run.stop_reason = f"maximum steps reached ({self.max_steps})"
            return True
        return False
