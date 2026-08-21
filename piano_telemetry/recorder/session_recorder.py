from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from queue import Empty
from threading import Event, RLock, Thread
from time import monotonic, perf_counter_ns
from typing import TextIO
from uuid import uuid4

from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.core.subscriber import OverflowPolicy, Subscription
from piano_telemetry.midi.event import MidiEvent

from .midi_exporter import MidiExportResult, export_jsonl_to_midi


class SessionState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    CLOSED = "closed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: str
    directory: Path
    started_at: str
    started_monotonic_ns: int
    piece: str | None
    target_bpm: float | None


@dataclass(frozen=True, slots=True)
class SessionResult:
    session_id: str
    directory: Path
    complete: bool
    event_count: int
    sequence_gap_events: int
    ingress_dropped_events: int
    subscriber_dropped_events: int
    midi_exported_events: int
    midi_skipped_events: int
    midi_export_error: str | None


class SessionRecorder:
    """Background JSONL recorder fed by an independent subscription queue."""

    def __init__(
        self,
        dispatcher: EventDispatcher[MidiEvent],
        *,
        sessions_dir: Path | str = Path("data/sessions"),
        queue_capacity: int = 8192,
        flush_interval_seconds: float = 1.0,
        finalization_timeout_seconds: float = 1.0,
    ) -> None:
        self.dispatcher = dispatcher
        self.sessions_dir = Path(sessions_dir)
        self.flush_interval_seconds = max(0.05, flush_interval_seconds)
        self.finalization_timeout_seconds = max(0.0, finalization_timeout_seconds)
        self.subscription: Subscription[MidiEvent] = dispatcher.subscribe(
            "recorder",
            capacity=queue_capacity,
            overflow=OverflowPolicy.DROP_NEWEST,
        )
        self._state = SessionState.IDLE
        self._lock = RLock()
        self._stop_worker = Event()
        self._worker: Thread | None = None
        self._info: SessionInfo | None = None
        self._events_file: TextIO | None = None
        self._stop_monotonic_ns: int | None = None
        self._last_flush_at = monotonic()
        self._event_count = 0
        self._first_seq: int | None = None
        self._last_seq: int | None = None
        self._sequence_gap_events = 0
        self._ingress_drop_baseline = 0
        self._subscriber_drop_baseline = 0

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._state

    def status(self) -> dict[str, object]:
        """Return a JSON-safe snapshot for control surfaces."""
        with self._lock:
            info = self._info
            active = self._state in {
                SessionState.RECORDING,
                SessionState.FINALIZING,
            }
            subscriber_drops = (
                max(
                    0,
                    self.subscription.stats().dropped_total
                    - self._subscriber_drop_baseline,
                )
                if active
                else 0
            )
            return {
                "state": self._state.value,
                "recording": self._state is SessionState.RECORDING,
                "finalizing": self._state is SessionState.FINALIZING,
                "session_id": info.session_id if info is not None else None,
                "started_at": info.started_at if info is not None else None,
                "piece": info.piece if info is not None else None,
                "target_bpm": info.target_bpm if info is not None else None,
                "event_count": self._event_count if active else 0,
                "subscriber_dropped_events": subscriber_drops,
                "sessions_dir": str(self.sessions_dir.resolve()),
            }

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.recover_aborted_sessions(self.sessions_dir)
        self._stop_worker.clear()
        self._worker = Thread(target=self._run, name="jsonl-recorder", daemon=True)
        self._worker.start()

    def close(self, *, timeout: float = 2.0) -> None:
        if self.state in {SessionState.RECORDING, SessionState.FINALIZING}:
            self.stop_session()
        self._stop_worker.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=timeout)
        self._worker = None

    def start_session(
        self,
        *,
        piece: str | None = None,
        target_bpm: float | None = None,
    ) -> SessionInfo:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                raise RuntimeError("recorder worker is not running")
            if self._state in {SessionState.RECORDING, SessionState.FINALIZING}:
                raise RuntimeError("a session is already active")

            session_id = uuid4().hex
            started_monotonic_ns = perf_counter_ns()
            started_at = _utc_now()
            directory = self.sessions_dir / session_id
            directory.mkdir(parents=True, exist_ok=False)
            events_part = directory / "events.jsonl.part"

            info = SessionInfo(
                session_id=session_id,
                directory=directory,
                started_at=started_at,
                started_monotonic_ns=started_monotonic_ns,
                piece=piece,
                target_bpm=target_bpm,
            )
            self._events_file = events_part.open("x", encoding="utf-8", buffering=64 * 1024)
            self._info = info
            self._stop_monotonic_ns = None
            self._event_count = 0
            self._first_seq = None
            self._last_seq = None
            self._sequence_gap_events = 0
            self._ingress_drop_baseline = self.dispatcher.metrics.ingress_drop_total
            self._subscriber_drop_baseline = self.subscription.stats().dropped_total
            self._last_flush_at = monotonic()
            self._state = SessionState.RECORDING
            self._write_session_metadata(state=SessionState.RECORDING, complete=None)
            return info

    def stop_session(self) -> SessionResult:
        with self._lock:
            if self._state is not SessionState.RECORDING or self._info is None:
                raise RuntimeError("no session is recording")
            self._state = SessionState.FINALIZING
            self._stop_monotonic_ns = perf_counter_ns()
            self._write_session_metadata(state=SessionState.FINALIZING, complete=None)

        deadline = monotonic() + self.finalization_timeout_seconds
        dispatcher_idle = self.dispatcher.wait_until_idle(
            timeout=max(0.0, deadline - monotonic())
        )
        while self.subscription.unfinished_tasks() > 0 and monotonic() < deadline:
            self._stop_worker.wait(0.005)

        with self._lock:
            assert self._info is not None
            info = self._info
            pending_at_close = self.subscription.unfinished_tasks()
            ingress_drops = max(
                0,
                self.dispatcher.metrics.ingress_drop_total - self._ingress_drop_baseline,
            )
            subscriber_drops = max(
                0,
                self.subscription.stats().dropped_total - self._subscriber_drop_baseline,
            )

            if self._events_file is not None:
                self._events_file.flush()
                self._events_file.close()
                self._events_file = None

            part_path = info.directory / "events.jsonl.part"
            events_path = info.directory / "events.jsonl"
            os.replace(part_path, events_path)

            export_result = self._export_midi(events_path, info.directory / "session.mid")
            complete = (
                self._sequence_gap_events == 0
                and ingress_drops == 0
                and subscriber_drops == 0
                and pending_at_close == 0
                and dispatcher_idle
            )
            summary = {
                "schema_version": 1,
                "session_id": info.session_id,
                "complete": complete,
                "event_count": self._event_count,
                "first_seq": self._first_seq,
                "last_seq": self._last_seq,
                "sequence_gap_events": self._sequence_gap_events,
                "ingress_dropped_events": ingress_drops,
                "subscriber_dropped_events": subscriber_drops,
                "pending_events_at_close": pending_at_close,
                "dispatcher_idle_at_close": dispatcher_idle,
                "midi_exported_events": export_result.exported_events,
                "midi_skipped_events": export_result.skipped_events,
                "midi_export_error": export_result.error,
            }
            _write_json_atomic(info.directory / "summary.json", summary)
            self._write_session_metadata(
                state=SessionState.CLOSED,
                complete=complete,
                ended_at=_utc_now(),
                summary=summary,
            )
            self._state = SessionState.CLOSED
            result = SessionResult(
                session_id=info.session_id,
                directory=info.directory,
                complete=complete,
                event_count=self._event_count,
                sequence_gap_events=self._sequence_gap_events,
                ingress_dropped_events=ingress_drops,
                subscriber_dropped_events=subscriber_drops,
                midi_exported_events=export_result.exported_events,
                midi_skipped_events=export_result.skipped_events,
                midi_export_error=export_result.error,
            )
            self._info = None
            self._stop_monotonic_ns = None
            return result

    def _run(self) -> None:
        while not self._stop_worker.is_set():
            try:
                event = self.subscription.get(timeout=0.05)
            except Empty:
                self._flush_if_due()
                continue
            try:
                self._record_event(event)
            finally:
                self.subscription.task_done()

    def _record_event(self, event: MidiEvent) -> None:
        with self._lock:
            info = self._info
            events_file = self._events_file
            if info is None or events_file is None:
                return
            if event.captured_monotonic_ns < info.started_monotonic_ns:
                return
            if (
                self._state is SessionState.FINALIZING
                and self._stop_monotonic_ns is not None
                and event.captured_monotonic_ns > self._stop_monotonic_ns
            ):
                return
            if self._state not in {SessionState.RECORDING, SessionState.FINALIZING}:
                return

            if self._last_seq is not None and event.seq > self._last_seq + 1:
                self._sequence_gap_events += event.seq - self._last_seq - 1
            if self._first_seq is None:
                self._first_seq = event.seq
            self._last_seq = event.seq

            payload = event.to_dict()
            payload["session_time_ns"] = (
                event.captured_monotonic_ns - info.started_monotonic_ns
            )
            events_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            events_file.write("\n")
            self._event_count += 1
            self._flush_if_due_locked()

    def _flush_if_due(self) -> None:
        with self._lock:
            self._flush_if_due_locked()

    def _flush_if_due_locked(self) -> None:
        if self._events_file is None:
            return
        now = monotonic()
        if now - self._last_flush_at >= self.flush_interval_seconds:
            self._events_file.flush()
            self._last_flush_at = now

    def _write_session_metadata(
        self,
        *,
        state: SessionState,
        complete: bool | None,
        ended_at: str | None = None,
        summary: dict[str, object] | None = None,
    ) -> None:
        assert self._info is not None
        info = self._info
        payload: dict[str, object] = {
            "schema_version": 1,
            "session_id": info.session_id,
            "state": state.value,
            "started_at": info.started_at,
            "started_monotonic_ns": info.started_monotonic_ns,
            "piece": info.piece,
            "target_bpm": info.target_bpm,
        }
        if complete is not None:
            payload["complete"] = complete
        if ended_at is not None:
            payload["ended_at"] = ended_at
        if summary is not None:
            payload["summary"] = summary
        _write_json_atomic(info.directory / "session.json", payload)

    @staticmethod
    def _export_midi(events_path: Path, output_path: Path) -> MidiExportResult:
        try:
            return export_jsonl_to_midi(events_path, output_path)
        except Exception as exc:
            _write_json_atomic(
                output_path.with_suffix(".error.json"),
                {"error": type(exc).__name__, "message": str(exc)},
            )
            return MidiExportResult(0, 0, output_path, error=str(exc))

    @staticmethod
    def recover_aborted_sessions(sessions_dir: Path | str) -> list[Path]:
        root = Path(sessions_dir)
        if not root.exists():
            return []
        recovered: list[Path] = []
        for part_path in root.glob("*/events.jsonl.part"):
            session_dir = part_path.parent
            metadata_path = session_dir / "session.json"
            metadata: dict[str, object]
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {
                    "schema_version": 1,
                    "session_id": session_dir.name,
                }
            metadata.update(
                {
                    "state": SessionState.ABORTED.value,
                    "complete": False,
                    "recovered_at": _utc_now(),
                }
            )
            recovered_events = session_dir / "events.jsonl"
            if recovered_events.exists():
                recovered_events = session_dir / "events.recovered.jsonl"
            try:
                os.replace(part_path, recovered_events)
                metadata["events_file"] = recovered_events.name
            except OSError as exc:
                metadata["recovery_error"] = str(exc)
            _write_json_atomic(metadata_path, metadata)
            recovered.append(session_dir)
        return recovered


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
