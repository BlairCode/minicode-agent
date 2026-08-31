from __future__ import annotations

from collections.abc import Callable
from threading import Event

from minicode_agent.llm.client import LLMClient, ModelError
from minicode_agent.llm.types import ModelResponse
from minicode_agent.session import SessionRecorder
from minicode_agent.tools.dispatcher import ToolDispatcher
from minicode_agent.tools.registry import ToolRegistry

from .context import ContextManager
from .explanation import describe_tool_calls
from .spec import AgentSpec
from .state import AgentRun, AgentState
from .stop import StopPolicy


class AgentRuntime:
    """Runs one shared observe-act-observe loop for every AgentSpec."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        dispatcher: ToolDispatcher,
        context: ContextManager,
        stop_policy: StopPolicy,
        spec: AgentSpec,
        *,
        model_retries: int = 2,
        retry_base_seconds: float = 0.5,
        recorder: SessionRecorder | None = None,
        event_handler: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.dispatcher = dispatcher
        self.context = context
        self.stop_policy = stop_policy
        self.spec = spec
        self.model_retries = model_retries
        self.retry_base_seconds = retry_base_seconds
        self.recorder = recorder
        self.event_handler = event_handler or (lambda _event, _payload: None)
        self.cancel_event = Event()
        self._active_run: AgentRun | None = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def _emit(self, event: str, payload: dict) -> None:
        self.event_handler(event, payload)
        if self.recorder:
            self.recorder.record(event, payload)

    def handle_external_event(self, event: str, payload: dict) -> None:
        if self._active_run and event == "approval_requested":
            self._active_run.state = AgentState.WAITING_APPROVAL
        elif self._active_run and event == "approval_resolved" and not self._active_run.finished:
            self._active_run.state = AgentState.RUNNING
        self._emit(event, payload)

    def _complete_with_retry(self) -> ModelResponse:
        last_error: ModelError | None = None
        for attempt in range(self.model_retries + 1):
            if self.cancel_event.is_set():
                break
            try:
                return self.llm.complete(
                    self.context.build(),
                    self.registry.schemas(self.spec.enabled_tools),
                )
            except ModelError as exc:
                last_error = exc
                if attempt >= self.model_retries:
                    break
                delay = self.retry_base_seconds * (2**attempt)
                self._emit("model_retry", {"attempt": attempt + 1, "delay_seconds": delay, "error": str(exc)})
                if delay and self.cancel_event.wait(delay):
                    break
        raise last_error or ModelError("model request cancelled")

    def step(self, run: AgentRun) -> bool:
        run.steps += 1
        self._emit("step", {"number": run.steps})
        try:
            response = self._complete_with_retry()
        except ModelError as exc:
            if self.cancel_event.is_set():
                run.state = AgentState.CANCELLED
                run.stop_reason = "cancelled by user"
                return True
            run.state = AgentState.FAILED
            run.stop_reason = str(exc)
            self._emit("model_error", {"error": str(exc)})
            return True

        if response.tool_calls:
            self.context.add_assistant_tool_calls(response.text, response.tool_calls)
            self._emit(
                "model_action",
                {
                    "description": describe_tool_calls(response.tool_calls),
                    "summary": response.text,
                    "tools": [call.name for call in response.tool_calls],
                },
            )
            for call in response.tool_calls:
                if self.cancel_event.is_set():
                    break
                run.tool_calls += 1
                result = self.dispatcher.dispatch(call, self.spec.enabled_tools)
                self.context.add_tool_result(call, result)
                self._emit("tool_recorded", {"name": call.name, "success": result.success, "fatal": result.fatal})
                if not result.success:
                    run.tool_errors += 1
                if result.fatal:
                    run.state = AgentState.FAILED
                    run.stop_reason = f"fatal tool error in {call.name}: {result.error}"
                    return True
            return False

        final_text = response.text.strip()
        if not final_text:
            run.state = AgentState.FAILED
            run.stop_reason = "model returned neither tool calls nor a final response"
            return True
        self.context.add_assistant(final_text)
        run.final_response = final_text
        run.state = AgentState.COMPLETED
        run.stop_reason = "model produced a final response"
        self._emit(
            "model_action",
            {"description": "整理执行结果并生成最终回答", "summary": "", "tools": []},
        )
        self._emit("final", {"text": final_text})
        return True

    def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> AgentRun:
        if not task.strip():
            raise ValueError("task cannot be empty")
        self.cancel_event.clear()
        run_options = {"task": task, "state": AgentState.RUNNING}
        if session_id:
            run_options["session_id"] = session_id
        run = AgentRun(**run_options)
        self._active_run = run
        self.context.add_user(task)
        if self.recorder:
            self.recorder.start(run.session_id)
        started_payload = {"session_id": run.session_id, "agent": self.spec.name, "task": task}
        if metadata:
            started_payload.update(metadata)
        self._emit("run_started", started_payload)
        try:
            while not run.finished:
                if self.stop_policy.apply_limits(run, self.cancel_event):
                    break
                if self.step(run):
                    break
        except KeyboardInterrupt:
            self.cancel_event.set()
            run.state = AgentState.CANCELLED
            run.stop_reason = "cancelled by user"
        self._emit(
            "run_finished",
            {
                "session_id": run.session_id,
                "state": run.state.value,
                "steps": run.steps,
                "tool_calls": run.tool_calls,
                "tool_errors": run.tool_errors,
                "reason": run.stop_reason,
            },
        )
        self._active_run = None
        return run
