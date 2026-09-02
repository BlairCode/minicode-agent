from __future__ import annotations

import http.client
import json
import re
import threading

from minicode_agent.web.server import create_server


class FakeHistory:
    def list_sessions(self):
        return []


class FakeController:
    def __init__(self) -> None:
        self.history = FakeHistory()
        self.started = None
        self.opened = None

    def bootstrap(self):
        return {
            "api_version": 2,
            "capabilities": ["conversation_uploads", "open_file_location"],
            "settings": {"provider": "qwen", "model": "qwen-plus"},
            "history": [],
            "agents": ["coding", "leetcode"],
            "default_agent": "coding",
        }

    def history_events(self, _session_id):
        return []

    def preview_file(self, _path, _workspace_id=""):
        return {"path": "demo.py", "content": "pass\n"}

    def start_run(self, task, agent, conversation_id="", files=None):
        self.started = (task, agent, conversation_id, files or [])
        return {"id": conversation_id or "a" * 32, "after": 8, "turn": 2 if conversation_id else 1, "uploaded_files": [item["name"] for item in files or []]}

    def open_file_location(self, path, workspace_id=""):
        self.opened = (path, workspace_id)
        return {"opened": True, "path": path}


def request(server, method: str, path: str, token: str | None = None, body: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    headers = {}
    if token is not None:
        headers["X-MiniCode-Token"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    result = response.status, dict(response.getheaders()), payload
    connection.close()
    return result


def test_local_server_serves_assets_and_protects_api() -> None:
    server, token = create_server(FakeController(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = request(server, "GET", "/")
        assert status == 200
        assert b"MiniCode Agent" in body
        assert b"MINI IN NAME" in body
        assert b'src="/logo.png"' in body
        assert b'id="agent-locked"' in body
        assert b'class="empty-icon"' not in body
        assert b"__MINICODE_SESSION_TOKEN__" not in body
        assert f'content="{token}"'.encode() in body
        assert "智能编程助手".encode() not in body
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Frame-Options"] == "DENY"

        status, headers, body = request(server, "GET", "/app.css")
        assert status == 200
        assert headers["Content-Type"] == "text/css; charset=utf-8"
        shell_rule = re.search(rb"\.app-shell\s*\{([^}]*)\}", body)
        assert shell_rule is not None
        assert b"grid-template-rows: minmax(0, 1fr)" in shell_rule.group(1)
        conversation_rule = re.search(rb"\.conversation\s*\{([^}]*)\}", body)
        assert conversation_rule is not None
        assert b"min-height: 0" in conversation_rule.group(1)
        assert b"height: 100%" not in conversation_rule.group(1)
        assert b"overflow-y: auto" in conversation_rule.group(1)

        status, headers, body = request(server, "GET", "/logo.png")
        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert body.startswith(b"\x89PNG\r\n\x1a\n")

        status, _, payload = request(server, "GET", "/api/bootstrap")
        assert status == 403
        assert json.loads(payload)["error"] == "invalid local session token"

        status, _, payload = request(server, "GET", "/api/bootstrap", token)
        assert status == 200
        bootstrap = json.loads(payload)
        assert bootstrap["settings"]["model"] == "qwen-plus"
        assert bootstrap["api_version"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_rejects_malformed_json_and_unknown_post_route() -> None:
    server, token = create_server(FakeController(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, payload = request(server, "POST", "/api/runs", token, "not-json")
        assert status == 400
        assert "valid UTF-8 JSON" in json.loads(payload)["error"]

        status, _, _ = request(server, "POST", "/not-an-api", token, "{}")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_passes_conversation_id_to_follow_up_run() -> None:
    controller = FakeController()
    server, token = create_server(controller, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conversation_id = "b" * 32
        body = json.dumps({"task": "继续完善", "agent": "coding", "conversation_id": conversation_id})
        status, _, payload = request(server, "POST", "/api/runs", token, body)

        assert status == 202
        assert json.loads(payload) == {"id": conversation_id, "after": 8, "turn": 2, "uploaded_files": []}
        assert controller.started == ("继续完善", "coding", conversation_id, [])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_passes_uploads_and_open_location_request() -> None:
    controller = FakeController()
    server, token = create_server(controller, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        files = [{"name": "main.py", "content": "print('ok')\n"}]
        body = json.dumps({"task": "检查文件", "agent": "coding", "files": files})
        status, _, payload = request(server, "POST", "/api/runs", token, body)
        assert status == 202
        assert json.loads(payload)["uploaded_files"] == ["main.py"]
        assert controller.started == ("检查文件", "coding", "", files)

        location_body = json.dumps({"path": "main.py", "workspace_id": "d" * 32})
        status, _, payload = request(server, "POST", "/api/file/open-location", token, location_body)
        assert status == 200
        assert json.loads(payload) == {"opened": True, "path": "main.py"}
        assert controller.opened == ("main.py", "d" * 32)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_second_server_cannot_reuse_an_active_port() -> None:
    first, _ = create_server(FakeController(), port=0)
    occupied_port = first.server_address[1]
    second = None
    try:
        second, _ = create_server(FakeController(), port=occupied_port)
        assert second.server_address[1] != occupied_port
    finally:
        first.server_close()
        if second is not None:
            second.server_close()
