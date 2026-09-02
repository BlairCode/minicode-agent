from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import ScriptedLLM
from minicode_agent.app import Application
from minicode_agent.llm.types import ModelResponse, ToolCall
from minicode_agent.personal import CredentialStore, PersonalSettings, PersonalSettingsStore
from minicode_agent.web.controller import PendingApproval, WebController, public_tool_arguments


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def make_controller(config, tmp_path: Path, responses: list[ModelResponse]) -> WebController:
    project_root = Path(__file__).resolve().parents[1]
    app = Application(config, project_root=project_root, llm=ScriptedLLM(responses))
    settings = PersonalSettings.from_config(config)
    return WebController(
        app,
        config,
        project_root,
        settings,
        PersonalSettingsStore(tmp_path / "personal-data"),
        CredentialStore(MemoryKeyring()),
    )


def wait_for_run(controller: WebController, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    snapshot = controller.run_events(run_id, -1)
    while snapshot["status"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = controller.run_events(run_id, -1)
    return snapshot


def test_public_tool_arguments_hides_file_contents() -> None:
    visible = public_tool_arguments({"path": "main.py", "content": "secret source", "old_text": "x" * 300})
    assert visible["path"] == "main.py"
    assert visible["content"] == "<content: 13 chars>"
    assert "secret source" not in json.dumps(visible)
    assert visible["old_text"].endswith("…")


def test_bootstrap_advertises_file_workflow_capabilities(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    payload = controller.bootstrap()
    assert payload["api_version"] == 2
    assert {"conversation_uploads", "open_file_location"}.issubset(payload["capabilities"])


def test_web_run_can_be_polled_to_completion(config, tmp_path: Path) -> None:
    controller = make_controller(
        config,
        tmp_path,
        [
            ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "answer.py", "content": "VALUE = 42\n"})]),
            ModelResponse(text="已创建并检查 answer.py。"),
        ],
    )
    response = controller.start_run("创建 answer.py", "coding")
    run_id = response["id"]
    snapshot = wait_for_run(controller, run_id)

    assert snapshot["status"] == "COMPLETED"
    assert any(item["event"] == "run_complete" for item in snapshot["events"])
    tool_call = next(item for item in snapshot["events"] if item["event"] == "tool_call")
    assert tool_call["payload"]["arguments"]["content"].startswith("<content:")
    conversation_workspace = controller.app.workspace / run_id
    assert (conversation_workspace / "answer.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert not (controller.app.workspace / "answer.py").exists()
    session = next(item for item in controller.history.list_sessions() if item["id"] == run_id)
    assert session["workspace_id"] == run_id


def test_follow_up_reuses_conversation_context_and_workspace(config, tmp_path: Path) -> None:
    controller = make_controller(
        config,
        tmp_path,
        [ModelResponse(text="第一轮回答"), ModelResponse(text="第二轮回答")],
    )

    first = controller.start_run("先创建一个基础版本", "coding")
    assert wait_for_run(controller, first["id"])["status"] == "COMPLETED"
    second = controller.start_run("继续完善它", "coding", first["id"])
    assert wait_for_run(controller, second["id"])["status"] == "COMPLETED"

    assert first["id"] == second["id"]
    assert second["turn"] == 2
    assert [path.name for path in controller.app.workspace.iterdir()] == [first["id"]]
    messages = controller.app.llm.calls[1][0]
    dialogue = [(item["role"], item.get("content")) for item in messages if item["role"] != "system"]
    assert dialogue[0][0] == "user"
    assert dialogue[0][1].startswith("先创建一个基础版本\n\n[Runtime workspace context]")
    assert "do not call list_directory" in dialogue[0][1]
    assert dialogue[1:] == [("assistant", "第一轮回答"), ("user", "继续完善它")]
    assert "list_directory" in {item["function"]["name"] for item in controller.app.llm.calls[1][1]}


def test_historical_conversation_can_resume_after_restart(config, tmp_path: Path) -> None:
    first_controller = make_controller(config, tmp_path, [ModelResponse(text="已完成初稿")])
    first = first_controller.start_run("编写初稿", "coding")
    assert wait_for_run(first_controller, first["id"])["status"] == "COMPLETED"

    second_controller = make_controller(config, tmp_path, [ModelResponse(text="已按要求修改")])
    resumed = second_controller.start_run("把标题改短一些", "coding", first["id"])
    assert wait_for_run(second_controller, resumed["id"])["status"] == "COMPLETED"

    messages = second_controller.app.llm.calls[0][0]
    dialogue = [(item["role"], item.get("content")) for item in messages if item["role"] != "system"]
    assert dialogue == [
        ("user", "编写初稿"),
        ("assistant", "已完成初稿"),
        ("user", "把标题改短一些"),
    ]
    assert resumed["turn"] == 2
    assert second_controller.runs[first["id"]].workspace == first_controller.runs[first["id"]].workspace


def test_existing_conversation_cannot_switch_agent(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    response = controller.start_run("开始任务", "coding")
    assert wait_for_run(controller, response["id"])["status"] == "COMPLETED"

    with pytest.raises(ValueError, match="agent cannot change"):
        controller.start_run("继续任务", "leetcode", response["id"])


def test_file_preview_stays_inside_workspace(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    (controller.app.workspace / "visible.txt").write_text("safe", encoding="utf-8")
    assert controller.preview_file("visible.txt")["content"] == "safe"
    with pytest.raises(PermissionError):
        controller.preview_file("../private.txt")


def test_file_preview_uses_conversation_workspace(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    workspace_id = "a" * 32
    conversation = controller.app.workspace / workspace_id
    conversation.mkdir()
    (conversation / "result.txt").write_text("isolated", encoding="utf-8")
    assert controller.preview_file("result.txt", workspace_id)["content"] == "isolated"
    with pytest.raises(PermissionError):
        controller.preview_file("../visible.txt", workspace_id)


def test_upload_is_isolated_and_only_file_name_reaches_model(config, tmp_path: Path) -> None:
    secret_content = "PRIVATE_UPLOAD_CONTENT = 42\n"
    controller = make_controller(config, tmp_path, [ModelResponse(text="已读取上传文件")])

    response = controller.start_run(
        "检查上传的配置",
        "coding",
        files=[{"name": "settings.toml", "content": secret_content}],
    )
    assert wait_for_run(controller, response["id"])["status"] == "COMPLETED"

    workspace = controller.app.workspace / response["id"]
    assert (workspace / "settings.toml").read_text(encoding="utf-8") == secret_content
    user_message = next(item["content"] for item in controller.app.llm.calls[0][0] if item["role"] == "user")
    assert "settings.toml" in user_message
    assert "Do not claim that the workspace or upload set is empty" in user_message
    assert secret_content.strip() not in user_message
    session_text = (controller.history.session_dir / f"{response['id']}.jsonl").read_text(encoding="utf-8")
    assert secret_content.strip() not in session_text
    assert response["uploaded_files"] == ["settings.toml"]


@pytest.mark.parametrize(
    "files, message",
    [
        ([{"name": "../escape.py", "content": "pass\n"}], "plain file names"),
        (
            [{"name": "same.py", "content": "a"}, {"name": "SAME.py", "content": "b"}],
            "duplicate uploaded file name",
        ),
    ],
)
def test_upload_rejects_unsafe_or_duplicate_names(config, tmp_path: Path, files, message: str) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    with pytest.raises(ValueError, match=message):
        controller.start_run("处理文件", "coding", files=files)


def test_follow_up_upload_does_not_overwrite_existing_file(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="first")])
    first = controller.start_run("开始", "coding", files=[{"name": "input.txt", "content": "original"}])
    assert wait_for_run(controller, first["id"])["status"] == "COMPLETED"

    with pytest.raises(ValueError, match="already exists"):
        controller.start_run(
            "继续",
            "coding",
            first["id"],
            files=[{"name": "input.txt", "content": "replacement"}],
        )
    assert (controller.app.workspace / first["id"] / "input.txt").read_text(encoding="utf-8") == "original"


def test_open_file_location_uses_conversation_workspace(config, tmp_path: Path, monkeypatch) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    workspace_id = "c" * 32
    workspace = controller.app.workspace / workspace_id
    workspace.mkdir()
    (workspace / "result.txt").write_text("safe", encoding="utf-8")
    opened: list[Path] = []
    monkeypatch.setattr("minicode_agent.web.controller.open_directory", opened.append)

    result = controller.open_file_location("result.txt", workspace_id)

    assert result == {"opened": True, "path": "result.txt"}
    assert opened == [workspace.resolve()]
    with pytest.raises(PermissionError):
        controller.open_file_location("../outside.txt", workspace_id)


def test_settings_store_never_receives_api_key(config, tmp_path: Path) -> None:
    controller = make_controller(config, tmp_path, [ModelResponse(text="done")])
    controller.save_settings({"model": "qwen-max", "api_key": "dashscope-private-value"})
    settings_text = controller.settings_store.path.read_text(encoding="utf-8")
    assert "dashscope-private-value" not in settings_text
    assert "api_key" not in settings_text
    assert controller.credential_store.get("qwen") == "dashscope-private-value"
    assert controller.public_settings()["credential_source"] == "system"


def test_browser_approval_resolution() -> None:
    controller = object.__new__(WebController)
    controller.approvals = {"approval": PendingApproval("run command", "run-id")}
    controller.lock = __import__("threading").RLock()
    controller.resolve_approval("approval", "a")
    assert controller.approvals["approval"].answer == "a"
    assert controller.approvals["approval"].completed.is_set()
