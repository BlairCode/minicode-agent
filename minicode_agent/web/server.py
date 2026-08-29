from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from minicode_agent.app import Application
from minicode_agent.config import AppConfig
from minicode_agent.personal import CredentialStore, PersonalSettings, PersonalSettingsStore

from .controller import WebController


STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
}
SESSION_TOKEN_MARKER = b"__MINICODE_SESSION_TOKEN__"


class LocalWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        controller: WebController,
        token: str,
        static_root: Path,
        image_root: Path,
    ) -> None:
        super().__init__(address, LocalRequestHandler)
        self.controller = controller
        self.token = token
        self.static_root = static_root
        self.image_root = image_root


class LocalRequestHandler(BaseHTTPRequestHandler):
    server: LocalWebServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Cache-Control", "no-store")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-MiniCode-Token", ""), self.server.token)

    def _require_api_auth(self) -> bool:
        if not self._authorized():
            self._error(HTTPStatus.FORBIDDEN, "invalid local session token")
            return False
        return True

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 0 or length > 1_000_000:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._require_api_auth():
                return
            self._handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._require_api_auth():
            return
        try:
            payload = self._read_json()
            self._handle_api_post(parsed.path, payload)
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/settings":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._require_api_auth():
            return
        try:
            self._json(HTTPStatus.OK, self.server.controller.save_settings(self._read_json()))
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/bootstrap":
                self._json(HTTPStatus.OK, self.server.controller.bootstrap())
                return
            if path == "/api/history":
                self._json(HTTPStatus.OK, self.server.controller.history.list_sessions())
                return
            if path.startswith("/api/history/"):
                self._json(HTTPStatus.OK, self.server.controller.history_events(path.rsplit("/", 1)[-1]))
                return
            if path == "/api/file":
                value = query.get("path", [""])[0]
                workspace_id = query.get("workspace_id", [""])[0]
                self._json(HTTPStatus.OK, self.server.controller.preview_file(value, workspace_id))
                return
            if path.startswith("/api/runs/"):
                run_id = path.rsplit("/", 1)[-1]
                try:
                    after = int(query.get("after", ["-1"])[0])
                except ValueError:
                    after = -1
                self._json(HTTPStatus.OK, self.server.controller.run_events(run_id, after))
                return
            self._error(HTTPStatus.NOT_FOUND, "API route not found")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_api_post(self, path: str, payload: dict) -> None:
        if path == "/api/runs":
            result = self.server.controller.start_run(
                str(payload.get("task", "")),
                str(payload.get("agent", "coding")),
                str(payload.get("conversation_id", "")),
            )
            self._json(HTTPStatus.ACCEPTED, result)
            return
        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run_id = path.split("/")[-2]
            self.server.controller.cancel_run(run_id)
            self._json(HTTPStatus.OK, {"cancelled": True})
            return
        if path.startswith("/api/approvals/"):
            approval_id = path.rsplit("/", 1)[-1]
            self.server.controller.resolve_approval(approval_id, str(payload.get("answer", "n")))
            self._json(HTTPStatus.OK, {"resolved": True})
            return
        self._error(HTTPStatus.NOT_FOUND, "API route not found")

    def _serve_static(self, path: str) -> None:
        files = {
            "/": self.server.static_root / "index.html",
            "/index.html": self.server.static_root / "index.html",
            "/app.css": self.server.static_root / "app.css",
            "/app.js": self.server.static_root / "app.js",
            "/logo.png": self.server.image_root / "logo.png",
        }
        file = files.get(path)
        if not file:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            body = file.read_bytes()
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        if file.name == "index.html":
            body = body.replace(SESSION_TOKEN_MARKER, self.server.token.encode("ascii"))
        self._send(HTTPStatus.OK, body, STATIC_TYPES[file.suffix])


def create_server(controller: WebController, port: int = 8765) -> tuple[LocalWebServer, str]:
    token = secrets.token_urlsafe(32)
    web_root = Path(__file__).resolve().parent
    static_root = web_root / "static"
    image_root = web_root / "imgs"
    try:
        server = LocalWebServer(("127.0.0.1", port), controller, token, static_root, image_root)
    except OSError:
        server = LocalWebServer(("127.0.0.1", 0), controller, token, static_root, image_root)
    return server, token


def run_web(
    app: Application,
    config: AppConfig,
    project_root: Path,
    settings: PersonalSettings,
    settings_store: PersonalSettingsStore,
    credential_store: CredentialStore | None,
    *,
    open_browser: bool = True,
) -> int:
    controller = WebController(app, config, project_root, settings, settings_store, credential_store)
    server, _token = create_server(controller, config.ui.web_port)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    print(f"MiniCode Web UI: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
