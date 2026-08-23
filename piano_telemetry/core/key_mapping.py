from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from typing import Protocol

from piano_telemetry.windows_keyboard import WindowsKeySender

from .config import default_data_dir


PIANO_NOTE_MIN = 21
PIANO_NOTE_MAX = 108
ALLOWED_KEY_CODES = tuple(
    [f"Digit{number}" for number in range(10)]
    + [f"Key{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
)
_ALLOWED_KEY_CODE_SET = frozenset(ALLOWED_KEY_CODES)


class KeySender(Protocol):
    def send(self, key_code: str, *, pressed: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class KeyboardMappingSettings:
    enabled: bool = False
    bindings: tuple[tuple[int, str], ...] = ()

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, object],
        *,
        strict: bool = False,
    ) -> "KeyboardMappingSettings":
        raw_bindings = payload.get("bindings", {})
        if not isinstance(raw_bindings, dict):
            if strict:
                raise ValueError("bindings 必须是对象")
            raw_bindings = {}

        bindings: dict[int, str] = {}
        for raw_note, raw_key in raw_bindings.items():
            try:
                note = int(raw_note)
            except (TypeError, ValueError):
                if strict:
                    raise ValueError(f"无效的 MIDI 音符：{raw_note}") from None
                continue
            if not PIANO_NOTE_MIN <= note <= PIANO_NOTE_MAX:
                if strict:
                    raise ValueError(f"MIDI 音符必须位于 {PIANO_NOTE_MIN}–{PIANO_NOTE_MAX}")
                continue
            if not isinstance(raw_key, str) or raw_key not in _ALLOWED_KEY_CODE_SET:
                if strict:
                    raise ValueError(f"不支持的键盘按键：{raw_key}")
                continue
            bindings[note] = raw_key

        return cls(
            enabled=bool(payload.get("enabled", False)),
            bindings=tuple(sorted(bindings.items())),
        )

    def binding_map(self) -> dict[int, str]:
        return dict(self.bindings)

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "bindings": {str(note): key for note, key in self.bindings},
        }


class KeyboardMappingStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_data_dir() / "key_mapping.json"
        self._lock = RLock()

    def load(self) -> KeyboardMappingSettings:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return KeyboardMappingSettings()
            if not isinstance(payload, dict):
                return KeyboardMappingSettings()
            return KeyboardMappingSettings.from_dict(payload)

    def save(self, settings: KeyboardMappingSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_text(
                json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)


class KeyboardMappingService:
    """Non-blocking MIDI-to-keyboard mapper with stuck-key recovery."""

    _STOP = object()

    def __init__(
        self,
        store: KeyboardMappingStore,
        *,
        sender: KeySender | None = None,
        queue_capacity: int = 512,
    ) -> None:
        self.store = store
        self._sender = sender
        self._settings_lock = RLock()
        self._state_lock = RLock()
        self._settings = store.load()
        self._bindings = self._settings.binding_map()
        self._queue: Queue[tuple[int, str, bool, int] | object] = Queue(
            maxsize=queue_capacity
        )
        self._stop_requested = Event()
        self._reset_requested = Event()
        self._thread: Thread | None = None
        self._accepting = False
        self._generation = 0
        self._active_notes: dict[int, str] = {}
        self._key_refcounts: dict[str, int] = {}
        self.dropped_events_total = 0
        self.send_errors_total = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        disabled_settings: KeyboardMappingSettings | None = None
        with self._settings_lock:
            if self._settings.enabled:
                self._settings = KeyboardMappingSettings(
                    enabled=False,
                    bindings=self._settings.bindings,
                )
                self._bindings = self._settings.binding_map()
                self._generation += 1
                disabled_settings = self._settings
        if disabled_settings is not None:
            try:
                self.store.save(disabled_settings)
            except OSError:
                # Runtime safety takes precedence if persistence is unavailable.
                pass
        self._stop_requested.clear()
        self._reset_requested.clear()
        self._accepting = True
        self._thread = Thread(
            target=self._run,
            name="midi-keyboard-mapper",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._accepting = False
        self.release_all()
        self._stop_requested.set()
        try:
            self._queue.put_nowait(self._STOP)
        except Full:
            self._reset_requested.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def offer_midi(self, message: list[int] | tuple[int, ...]) -> bool:
        """Resolve and enqueue a note transition without blocking the MIDI callback."""
        if not self._accepting or len(message) < 3:
            return False
        status = int(message[0]) & 0xF0
        if status not in {0x80, 0x90}:
            return False
        note = int(message[1]) & 0x7F
        pressed = status == 0x90 and (int(message[2]) & 0x7F) > 0
        with self._settings_lock:
            if not self._settings.enabled:
                return False
            key_code = self._bindings.get(note)
            generation = self._generation
        if key_code is None:
            return False
        try:
            self._queue.put_nowait((note, key_code, pressed, generation))
            return True
        except Full:
            self.dropped_events_total += 1
            self._reset_requested.set()
            return False

    def apply(self, settings: KeyboardMappingSettings) -> KeyboardMappingSettings:
        self.store.save(settings)
        with self._settings_lock:
            self._settings = settings
            self._bindings = settings.binding_map()
            self._generation += 1
        self.release_all()
        return settings

    def release_all(self) -> None:
        self._discard_pending()
        with self._state_lock:
            for key_code in tuple(self._key_refcounts):
                self._send(key_code, pressed=False)
            self._active_notes.clear()
            self._key_refcounts.clear()
        self._reset_requested.clear()

    def status(self) -> dict[str, object]:
        with self._settings_lock, self._state_lock:
            result = self._settings.to_dict()
            result.update(
                {
                    "active_notes": sorted(self._active_notes),
                    "dropped_events_total": self.dropped_events_total,
                    "send_errors_total": self.send_errors_total,
                }
            )
            return result

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            if self._reset_requested.is_set():
                self.release_all()
            try:
                item = self._queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                if item is self._STOP:
                    return
                note, key_code, pressed, generation = item
                with self._settings_lock:
                    if generation != self._generation:
                        continue
                    with self._state_lock:
                        if pressed:
                            self._press(note, key_code)
                        else:
                            self._release(note)
            finally:
                self._queue.task_done()

    def _press(self, note: int, key_code: str) -> None:
        if note in self._active_notes:
            return
        self._active_notes[note] = key_code
        references = self._key_refcounts.get(key_code, 0)
        self._key_refcounts[key_code] = references + 1
        if references == 0:
            self._send(key_code, pressed=True)

    def _release(self, note: int) -> None:
        key_code = self._active_notes.pop(note, None)
        if key_code is None:
            return
        references = self._key_refcounts.get(key_code, 0) - 1
        if references <= 0:
            self._key_refcounts.pop(key_code, None)
            self._send(key_code, pressed=False)
        else:
            self._key_refcounts[key_code] = references

    def _send(self, key_code: str, *, pressed: bool) -> None:
        try:
            if self._sender is None:
                self._sender = WindowsKeySender()
            self._sender.send(key_code, pressed=pressed)
        except Exception:
            self.send_errors_total += 1

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return
            else:
                self._queue.task_done()
