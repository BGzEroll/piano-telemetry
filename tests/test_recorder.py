from __future__ import annotations

import json
from pathlib import Path

from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.recorder.session_recorder import SessionRecorder, SessionState


def event(seq: int, timestamp: int) -> MidiEvent:
    return MidiEvent.from_raw(
        seq=seq,
        captured_monotonic_ns=timestamp,
        source_port="test piano",
        raw=[0x90 if seq % 2 else 0x80, 60, 90 if seq % 2 else 0],
    )


def test_session_records_jsonl_and_exports_midi(tmp_path: Path) -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=32)
    recorder = SessionRecorder(
        dispatcher,
        sessions_dir=tmp_path,
        finalization_timeout_seconds=1.0,
    )
    recorder.start()
    dispatcher.start()
    try:
        info = recorder.start_session(piece="Test Piece", target_bpm=80)
        assert dispatcher.publish_nowait(event(1, info.started_monotonic_ns + 1))
        assert dispatcher.publish_nowait(event(2, info.started_monotonic_ns + 2))
        result = recorder.stop_session()
    finally:
        recorder.close()
        dispatcher.stop()

    assert result.complete
    assert result.event_count == 2
    assert result.midi_exported_events == 2
    assert result.midi_export_error is None
    assert (info.directory / "events.jsonl").is_file()
    assert not (info.directory / "events.jsonl.part").exists()
    assert (info.directory / "session.mid").is_file()

    lines = (info.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert [payload["seq"] for payload in payloads] == [1, 2]
    assert payloads[0]["session_time_ns"] >= 0
    metadata = json.loads((info.directory / "session.json").read_text(encoding="utf-8"))
    assert metadata["state"] == "closed"
    assert metadata["complete"] is True


def test_sequence_gap_marks_session_incomplete(tmp_path: Path) -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=32)
    recorder = SessionRecorder(dispatcher, sessions_dir=tmp_path)
    recorder.start()
    dispatcher.start()
    try:
        info = recorder.start_session()
        dispatcher.publish_nowait(event(10, info.started_monotonic_ns + 1))
        dispatcher.publish_nowait(event(13, info.started_monotonic_ns + 2))
        result = recorder.stop_session()
    finally:
        recorder.close()
        dispatcher.stop()

    assert not result.complete
    assert result.sequence_gap_events == 2


def test_ingress_drop_marks_session_incomplete(tmp_path: Path) -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=32)
    recorder = SessionRecorder(dispatcher, sessions_dir=tmp_path)
    recorder.start()
    dispatcher.start()
    try:
        recorder.start_session()
        dispatcher.metrics.ingress_drop_total += 1
        result = recorder.stop_session()
    finally:
        recorder.close()
        dispatcher.stop()

    assert not result.complete
    assert result.ingress_dropped_events == 1


def test_recovery_marks_part_session_aborted(tmp_path: Path) -> None:
    session_dir = tmp_path / "unfinished"
    session_dir.mkdir()
    (session_dir / "events.jsonl.part").write_text("", encoding="utf-8")
    (session_dir / "session.json").write_text(
        json.dumps({"session_id": "unfinished", "state": "recording"}),
        encoding="utf-8",
    )

    recovered = SessionRecorder.recover_aborted_sessions(tmp_path)

    assert recovered == [session_dir]
    metadata = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert metadata["state"] == SessionState.ABORTED.value
    assert metadata["complete"] is False
    assert metadata["events_file"] == "events.jsonl"
    assert (session_dir / "events.jsonl").is_file()
    assert not (session_dir / "events.jsonl.part").exists()
