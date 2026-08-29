from __future__ import annotations

import json
from typing import Any

from minicode_agent.agent.state import AgentRun, AgentState


class Renderer:
    def __init__(self, *, show_command_output: bool = True) -> None:
        self.show_command_output = show_command_output
        try:
            from rich.console import Console

            self.console = Console(highlight=False)
            self.rich = True
        except ImportError:
            self.console = None
            self.rich = False

    def print(self, message: str = "", *, style: str | None = None) -> None:
        if self.rich:
            self.console.print(message, style=style)
        else:
            print(message)

    def header(self, agent: str, workspace: str, security: str, model: str) -> None:
        if self.rich:
            from rich.panel import Panel
            from rich.table import Table

            table = Table.grid(padding=(0, 2))
            table.add_column(style="dim")
            table.add_column()
            table.add_row("Agent", agent.title())
            table.add_row("Workspace", workspace)
            table.add_row("Security", security.upper())
            table.add_row("Model", model)
            self.console.print(Panel(table, title="MiniCode Agent", border_style="cyan"))
        else:
            self.print(f"MiniCode Agent | {agent} | {workspace} | {security} | {model}")

    def event(self, event: str, payload: dict[str, Any]) -> None:
        if event == "step":
            self.print(f"\nStep {payload['number']}", style="dim")
        elif event == "model_retry":
            self.print(f"Model retry {payload['attempt']}: {payload['error']}", style="yellow")
        elif event == "tool_call":
            arguments = json.dumps(payload["arguments"], ensure_ascii=False)
            if len(arguments) > 240:
                arguments = arguments[:240] + "..."
            self.print(f"→ {payload['name']}  {arguments}", style="cyan")
        elif event == "tool_result":
            result = payload["result"]
            status = "OK" if result["success"] else "FAILED"
            style = "green" if result["success"] else "red"
            self.print(f"  {status}", style=style)
            if self.show_command_output or payload["name"] != "run_command":
                content = result.get("output") or result.get("error") or ""
                if content:
                    self.print("  " + str(content).replace("\n", "\n  "))
        elif event == "approval_requested":
            self.print("  Waiting for approval...", style="yellow")

    def final(self, run: AgentRun) -> None:
        if run.state is AgentState.COMPLETED:
            self.print("\n✓ Task completed", style="bold green")
            self.print(run.final_response)
        else:
            self.print(f"\nTask stopped: {run.state.value}", style="bold red")
            self.print(run.stop_reason)
        self.print(
            f"Steps {run.steps} · Tool calls {run.tool_calls} · Tool errors {run.tool_errors}",
            style="dim",
        )
