from __future__ import annotations

from minicode_agent.app import Application
from minicode_agent.cli.renderer import Renderer


HELP = """Commands:
  /help                 Show this help
  /agent coding         Switch to the general coding agent
  /agent leetcode       Switch to the algorithm agent
  /mode <name>           Set LeetCode solve/hint/interview/review mode
  /workspace [path]     Show or change the workspace
  /settings             Show active non-secret settings
  /skills               Show enabled skills
  /clear                Clear conversation history
  /history              Show current message count
  /exit                  Exit
"""


def run_console(app: Application) -> int:
    renderer = Renderer(show_command_output=app.config.ui.show_command_output)
    agent_name = app.config.agent.default
    runtime = app.create_runtime(agent_name, event_handler=renderer.event)

    def rebuild() -> None:
        nonlocal runtime
        runtime = app.create_runtime(agent_name, event_handler=renderer.event)

    renderer.header(agent_name, str(app.workspace), app.config.security.command_mode, app.config.model.model)
    renderer.print("Type a task, or /help for commands.\n", style="dim")
    while True:
        try:
            task = input("minicode> ").strip()
        except (EOFError, KeyboardInterrupt):
            renderer.print("\nBye.")
            return 0
        if not task:
            continue
        if task == "/exit":
            renderer.print("Bye.")
            return 0
        if task == "/help":
            renderer.print(HELP)
            continue
        if task.startswith("/agent"):
            parts = task.split(maxsplit=1)
            if len(parts) != 2 or parts[1] not in {"coding", "leetcode"}:
                renderer.print("Usage: /agent coding|leetcode", style="yellow")
                continue
            agent_name = parts[1]
            rebuild()
            renderer.print(f"Active agent: {agent_name}", style="green")
            continue
        if task.startswith("/workspace"):
            parts = task.split(maxsplit=1)
            if len(parts) == 1:
                renderer.print(str(app.workspace))
            else:
                app.set_workspace(parts[1])
                rebuild()
                renderer.print(f"Workspace: {app.workspace}", style="green")
            continue
        if task.startswith("/mode"):
            parts = task.split(maxsplit=1)
            if len(parts) != 2 or parts[1] not in {"solve", "hint", "interview", "review"}:
                renderer.print("Usage: /mode solve|hint|interview|review", style="yellow")
                continue
            app.config.leetcode.mode = parts[1]
            rebuild()
            renderer.print(f"LeetCode mode: {parts[1]}", style="green")
            continue
        if task == "/settings":
            renderer.print(
                f"provider={app.config.model.provider}\nmodel={app.config.model.model}\n"
                f"base_url={app.config.model.base_url}\ncommand_mode={app.config.security.command_mode}\n"
                f"network_access={app.config.security.network_access}\n"
                f"code_style={app.config.coding.code_style}\n"
                f"comment_level={app.config.coding.comment_level}\n"
                f"history_dir={app.data_dir}\nmax_steps={app.config.agent.max_steps}"
            )
            continue
        if task == "/skills":
            renderer.print("\n".join(runtime.spec.enabled_skills))
            continue
        if task == "/clear":
            runtime.context.clear_history()
            renderer.print("Conversation history cleared.", style="green")
            continue
        if task == "/history":
            renderer.print(
                f"Messages: {len(runtime.context.messages)}; trimmed on last build: {runtime.context.trimmed_messages}"
            )
            continue
        if task.startswith("/"):
            renderer.print("Unknown command. Use /help.", style="yellow")
            continue
        try:
            run = runtime.run(task)
        except Exception as exc:
            renderer.print(f"Cannot start task: {type(exc).__name__}: {exc}", style="red")
            continue
        renderer.final(run)
