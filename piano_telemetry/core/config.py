from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock


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
    input_port: str | None = None
    output_port: str | None = None
    receive_sysex: bool = False
    receive_clock: bool = False
    receive_active_sensing: bool = False
    panic_on_stop: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppSettings":
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in payload.items() if key in allowed}
        for key in ("input_port", "output_port"):
            value = values.get(key)
            if value is not None and not isinstance(value, str):
                values[key] = None
            elif isinstance(value, str):
                values[key] = value.strip() or None
        for key in (
            "receive_sysex",
            "receive_clock",
            "receive_active_sensing",
            "panic_on_stop",
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
