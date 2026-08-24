from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from piano_telemetry.core.config import (
    DEFAULT_PUSH_TOKEN,
    AppSettings,
)


REQUIRED_SESSION_FILES = (
    "session.json",
    "summary.json",
    "events.jsonl",
    "session.mid",
)
_WINDOWS_INVALID = re.compile(r'[\\/:*?"<>|]')
_SESSION_ID = re.compile(r"^[0-9a-fA-F]{32}$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class OpenClawPushError(RuntimeError):
    def __init__(self, kind: str, message: str, *, remote_status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.remote_status = remote_status


@dataclass(frozen=True, slots=True)
class PushResult:
    session_id: str
    duplicate: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ok",
            "session_id": self.session_id,
            "duplicate": self.duplicate,
            "message": self.message,
        }


def normalize_server_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ValueError("服务器地址必须是有效的 http:// 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务器地址不能包含账号、查询参数或片段")
    path = parsed.path.rstrip("/")
    return urlunsplit(("http", parsed.netloc, path, "", ""))


def token_is_configured(token: str) -> bool:
    return bool(token) and token != DEFAULT_PUSH_TOKEN


def sanitize_zip_stem(save_name: str | None, session_id: str) -> str:
    name = _WINDOWS_INVALID.sub("_", (save_name or "").strip()).rstrip(" .")
    if not name or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        name = f"session_{session_id[:8]}"
    return name[:100].rstrip(" .") or f"session_{session_id[:8]}"


def build_session_zip(
    session_directory: Path | str,
    save_name: str | None,
    session_id: str,
    output_directory: Path | str,
) -> Path:
    source = Path(session_directory).resolve()
    if not source.is_dir():
        raise OpenClawPushError("session_missing", "录制目录不存在")
    files: list[Path] = []
    for filename in REQUIRED_SESSION_FILES:
        path = (source / filename).resolve()
        if path.parent != source or not path.is_file():
            raise OpenClawPushError(
                "archive_invalid",
                f"录制文件不完整：缺少 {filename}",
            )
        files.append(path)

    target_root = Path(output_directory)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"{sanitize_zip_stem(save_name, session_id)}.zip"
    with ZipFile(
        target,
        mode="x",
        compression=ZIP_DEFLATED,
        compresslevel=1,
    ) as archive:
        for path, filename in zip(files, REQUIRED_SESSION_FILES, strict=True):
            archive.write(path, arcname=filename)
    return target


class PushHistoryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def is_pushed(self, server_url: str, session_id: str) -> bool:
        with self._lock:
            try:
                key = _history_key(server_url, session_id)
            except ValueError:
                return False
            return key in self._load_unlocked()

    def mark_pushed(
        self,
        server_url: str,
        session_id: str,
        *,
        duplicate: bool,
    ) -> None:
        with self._lock:
            history = self._load_unlocked()
            history[_history_key(server_url, session_id)] = {
                "server_url": normalize_server_url(server_url),
                "session_id": session_id,
                "pushed_at": datetime.now(UTC).isoformat(),
                "duplicate": duplicate,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_text(
                json.dumps(history, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)

    def _load_unlocked(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): value
            for key, value in payload.items()
            if isinstance(value, dict)
        }


class SessionPushService:
    def __init__(
        self,
        sessions_dir: Path | str,
        history_store: PushHistoryStore,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.history_store = history_store
        self.timeout_seconds = timeout_seconds
        self._lock = RLock()
        self._inflight: set[tuple[str, str]] = set()

    def push(self, session_id: str, settings: AppSettings) -> PushResult:
        if not settings.push_enabled:
            raise OpenClawPushError("disabled", "OpenClaw 推送功能未启用")
        if not token_is_configured(settings.push_token):
            raise OpenClawPushError("token_missing", "请先在设置中填写推送密钥")
        try:
            server_url = normalize_server_url(settings.push_server_url)
        except ValueError as exc:
            raise OpenClawPushError("url_invalid", str(exc)) from exc
        if not _SESSION_ID.fullmatch(session_id):
            raise OpenClawPushError("session_missing", "无效的录制 session_id")

        key = (server_url, session_id.lower())
        if self.history_store.is_pushed(server_url, session_id):
            return PushResult(session_id, True, "已推送")
        with self._lock:
            if key in self._inflight:
                raise OpenClawPushError("in_progress", "该录制正在推送中")
            self._inflight.add(key)
        try:
            directory, save_name = _find_session(self.sessions_dir, session_id)
            with tempfile.TemporaryDirectory(prefix="piano-telemetry-push-") as temporary:
                archive = build_session_zip(
                    directory,
                    save_name,
                    session_id,
                    temporary,
                )
                duplicate = _upload_archive(
                    server_url,
                    settings.push_token,
                    archive,
                    session_id,
                    timeout_seconds=self.timeout_seconds,
                )
            self.history_store.mark_pushed(
                server_url,
                session_id,
                duplicate=duplicate,
            )
            return PushResult(
                session_id,
                duplicate,
                "服务端已存在" if duplicate else "已推送",
            )
        finally:
            with self._lock:
                self._inflight.discard(key)

    def list_sessions(self, settings: AppSettings) -> list[dict[str, object]]:
        try:
            server_url = normalize_server_url(settings.push_server_url)
        except ValueError:
            server_url = settings.push_server_url
        return list_saved_sessions(
            self.sessions_dir,
            history_store=self.history_store,
            server_url=server_url,
        )


def list_saved_sessions(
    sessions_dir: Path | str,
    *,
    history_store: PushHistoryStore,
    server_url: str,
) -> list[dict[str, object]]:
    root = Path(sessions_dir)
    results: list[dict[str, object]] = []
    try:
        directories = tuple(root.iterdir())
    except (FileNotFoundError, OSError):
        return results
    for directory in directories:
        if not directory.is_dir():
            continue
        metadata = _read_json(directory / "session.json")
        summary = _read_json(directory / "summary.json")
        session_id = metadata.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            continue
        if not all((directory / name).is_file() for name in REQUIRED_SESSION_FILES):
            continue
        results.append(
            {
                "session_id": session_id,
                "save_name": directory.name,
                "started_at": metadata.get("started_at"),
                "ended_at": metadata.get("ended_at"),
                "complete": bool(summary.get("complete", metadata.get("complete", False))),
                "event_count": _safe_int(summary.get("event_count")),
                "pushed": history_store.is_pushed(server_url, session_id),
            }
        )
    results.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return results


def _find_session(sessions_dir: Path, session_id: str) -> tuple[Path, str]:
    root = sessions_dir.resolve()
    try:
        directories = tuple(root.iterdir())
    except (FileNotFoundError, OSError) as exc:
        raise OpenClawPushError("session_missing", "录制目录不存在") from exc
    for directory in directories:
        if not directory.is_dir():
            continue
        metadata = _read_json(directory / "session.json")
        if metadata.get("session_id") != session_id:
            continue
        resolved = directory.resolve()
        if resolved.parent != root:
            break
        return resolved, directory.name
    raise OpenClawPushError("session_missing", "找不到指定录制")


def _upload_archive(
    server_url: str,
    token: str,
    archive_path: Path,
    session_id: str,
    *,
    timeout_seconds: float,
) -> bool:
    parsed = urlsplit(server_url)
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port or 80,
        timeout=timeout_seconds,
    )
    boundary = f"----PianoTelemetry{uuid4().hex}"
    display_name = archive_path.name
    ascii_fallback = f"session_{session_id[:8]}.zip"
    disposition = (
        f'Content-Disposition: form-data; name="file"; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(display_name, safe='')}\r\n"
    )
    preamble = (
        f"--{boundary}\r\n"
        f"{disposition}"
        "Content-Type: application/zip\r\n\r\n"
    ).encode("ascii")
    closing = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = len(preamble) + archive_path.stat().st_size + len(closing)
    upload_path = f"{parsed.path.rstrip('/')}/upload" or "/upload"
    if not upload_path.startswith("/"):
        upload_path = f"/{upload_path}"

    try:
        connection.putrequest("POST", upload_path)
        connection.putheader("X-Auth-Token", token)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.putheader("Connection", "close")
        connection.endheaders()
        connection.send(preamble)
        with archive_path.open("rb") as archive_file:
            while chunk := archive_file.read(64 * 1024):
                connection.send(chunk)
        connection.send(closing)
        response = connection.getresponse()
        body = response.read()
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise OpenClawPushError("unreachable", "服务器不可达") from exc
    finally:
        connection.close()

    payload: dict[str, object] = {}
    if body:
        try:
            decoded = json.loads(body.decode("utf-8"))
            if isinstance(decoded, dict):
                payload = decoded
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
    remote_session = payload.get("session_id")
    if isinstance(remote_session, str) and remote_session != session_id:
        raise OpenClawPushError("invalid_response", "服务器返回了不匹配的 session_id")
    if response.status == 200:
        return bool(payload.get("duplicate", False))
    if response.status == 409:
        return True
    if response.status == 401:
        raise OpenClawPushError("token_error", "密钥错误", remote_status=401)
    if response.status == 400:
        raise OpenClawPushError(
            "archive_invalid",
            "录制文件不完整或压缩包无效",
            remote_status=400,
        )
    raise OpenClawPushError(
        "server_error",
        f"服务器错误（{response.status}）",
        remote_status=response.status,
    )


def _history_key(server_url: str, session_id: str) -> str:
    return f"{normalize_server_url(server_url)}|{session_id.lower()}"


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
