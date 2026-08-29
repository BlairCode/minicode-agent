from __future__ import annotations

import http.client
import json
import threading

from minicode_agent.web.server import create_server


class FakeHistory:
    def list_sessions(self):
        return []


class FakeController:
    def __init__(self) -> None:
        self.history = FakeHistory()
        self.started = None

    def bootstrap(self):
        return {
            "settings": {"provider": "qwen", "model": "qwen-plus"},
            "history": [],
            "agents": ["coding", "leetcode"],
            "default_agent": "coding",
        }

    def history_events(self, _session_id):
        return []

    def preview_file(self, _path, _workspace_id=""):
        return {"path": "demo.py", "content": "pass\n"}

    def start_run(self, task, agent, conversation_id=""):
        self.started = (task, agent, conversation_id)
        return {"id": conversation_id or "a" * 32, "after": 8, "turn": 2 if conversation_id else 1}


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

        status, headers, body = request(server, "GET", "/logo.png")
        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert body.startswith(b"\x89PNG\r\n\x1a\n")

        status, _, payload = request(server, "GET", "/api/bootstrap")
        assert status == 403
        assert json.loads(payload)["error"] == "invalid local session token"

        status, _, payload = request(server, "GET", "/api/bootstrap", token)
        assert status == 200
        assert json.loads(payload)["settings"]["model"] == "qwen-plus"
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
        assert json.loads(payload) == {"id": conversation_id, "after": 8, "turn": 2}
        assert controller.started == ("继续完善", "coding", conversation_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
