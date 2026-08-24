from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock

from piano_telemetry.analyzer.tonality import DEFAULT_TONALITY, normalize_tonality
from piano_telemetry.midi.virtual_midi import VIRTUAL_INPUT_PORT_NAME


DEFAULT_PUSH_SERVER_URL = "http://192.168.114.103:8767"
DEFAULT_PUSH_TOKEN = "CHANGE_ME"


def application_directory() -> Path:
    """Directory containing the EXE, or the current directory in source mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def default_data_dir() -> Path:
    return application_directory() / "data"


def default_sessions_dir() -> Path:
    return default_data_dir() / "sessions"


@dataclass(frozen=True, slots=True)
class AppSettings:
    input_port: str = VIRTUAL_INPUT_PORT_NAME
    tonality: str = DEFAULT_TONALITY
    receive_sysex: bool = False
    receive_clock: bool = False
    receive_active_sensing: bool = False
    panic_on_stop: bool = True
    push_enabled: bool = False
    push_server_url: str = DEFAULT_PUSH_SERVER_URL
    push_token: str = DEFAULT_PUSH_TOKEN

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppSettings":
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in payload.items() if key in allowed}
        if "input_port" in values:
            input_port = values["input_port"]
            values["input_port"] = (
                input_port.strip()
                if isinstance(input_port, str) and input_port.strip()
                else VIRTUAL_INPUT_PORT_NAME
            )
        if "tonality" in values:
            values["tonality"] = normalize_tonality(values["tonality"])
        if "push_server_url" in values:
            server_url = values["push_server_url"]
            values["push_server_url"] = (
                server_url.strip()
                if isinstance(server_url, str) and server_url.strip()
                else DEFAULT_PUSH_SERVER_URL
            )
        if "push_token" in values and not isinstance(values["push_token"], str):
            values["push_token"] = DEFAULT_PUSH_TOKEN
        for key in (
            "receive_sysex",
            "receive_clock",
            "receive_active_sensing",
            "panic_on_stop",
            "push_enabled",
        ):
            if key in values:
                values[key] = bool(values[key])
        return cls(**values)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SettingsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_data_dir() / "config.json"
        self._lock = RLock()

    def load(self) -> AppSettings:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return AppSettings()
            except (OSError, json.JSONDecodeError):
                return AppSettings()
            if not isinstance(payload, dict):
                return AppSettings()
            return AppSettings.from_dict(payload)

    def save(self, settings: AppSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_text(
                json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
