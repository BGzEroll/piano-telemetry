import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote
from zipfile import ZipFile

import pytest

from piano_telemetry.core.config import AppSettings
from piano_telemetry.push.openclaw import (
    OpenClawPushError,
    PushHistoryStore,
    SessionPushService,
    build_session_zip,
)


SESSION_ID = "0123456789abcdef0123456789abcdef"


def create_session(root: Path, name: str = "鸟之诗 练习") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(
        json.dumps({"session_id": SESSION_ID, "started_at": "2026-08-24T08:00:00+00:00"}),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(
        json.dumps({"complete": True, "event_count": 12}),
        encoding="utf-8",
    )
    (directory / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (directory / "session.mid").write_bytes(b"MThd")
    return directory


class UploadHandler(BaseHTTPRequestHandler):
    response_status = 200
    received_headers = None
    received_body = b""

    def do_POST(self) -> None:
        type(self).received_headers = self.headers
        type(self).received_body = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps(
            {
                "status": "ok" if self.response_status == 200 else "duplicate",
                "session_id": SESSION_ID,
                "duplicate": self.response_status == 409,
            }
        ).encode()
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


@contextmanager
def upload_server(status: int):
    UploadHandler.response_status = status
    UploadHandler.received_headers = None
    UploadHandler.received_body = b""
    server = ThreadingHTTPServer(("127.0.0.1", 0), UploadHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_archive_keeps_chinese_name_and_has_four_ascii_root_files(tmp_path: Path) -> None:
    session = create_session(tmp_path / "sessions")
    archive = build_session_zip(session, "鸟之诗：测试/一", SESSION_ID, tmp_path / "out")

    assert archive.name == "鸟之诗：测试_一.zip"
    with ZipFile(archive) as bundle:
        assert bundle.namelist() == [
            "session.json",
            "summary.json",
            "events.jsonl",
            "session.mid",
        ]


@pytest.mark.parametrize(
    ("status", "duplicate", "error_kind"),
    [(200, False, None), (409, True, None), (401, None, "token_error")],
)
def test_push_status_mapping_and_unicode_multipart_filename(
    tmp_path: Path,
    status: int,
    duplicate: bool | None,
    error_kind: str | None,
) -> None:
    sessions = tmp_path / "sessions"
    create_session(sessions)
    history = PushHistoryStore(tmp_path / "push_history.json")
    service = SessionPushService(sessions, history)

    with upload_server(status) as server_url:
        settings = AppSettings(
            push_enabled=True,
            push_server_url=server_url,
            push_token="real-secret",
        )
        if error_kind:
            with pytest.raises(OpenClawPushError) as caught:
                service.push(SESSION_ID, settings)
            assert caught.value.kind == error_kind
            assert not history.is_pushed(server_url, SESSION_ID)
        else:
            result = service.push(SESSION_ID, settings)
            assert result.duplicate is duplicate
            assert history.is_pushed(server_url, SESSION_ID)

        assert UploadHandler.received_headers["Connection"] == "close"
        assert UploadHandler.received_headers["X-Auth-Token"] == "real-secret"
        encoded_name = quote("鸟之诗 练习.zip", safe="").encode("ascii")
        assert b"filename*=UTF-8''" + encoded_name in UploadHandler.received_body


def test_history_is_scoped_to_remote_server(tmp_path: Path) -> None:
    history = PushHistoryStore(tmp_path / "push_history.json")
    history.mark_pushed("http://server-a:8767", SESSION_ID, duplicate=False)

    assert history.is_pushed("http://server-a:8767/", SESSION_ID)
    assert not history.is_pushed("http://server-b:8767", SESSION_ID)
