from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MidiExportResult:
    exported_events: int
    skipped_events: int
    output_path: Path
    error: str | None = None


def export_jsonl_to_midi(events_path: Path, output_path: Path) -> MidiExportResult:
    """Export channel messages while preserving wall-clock spacing to 1 ms."""
    import mido

    midi_file = mido.MidiFile(type=0, ticks_per_beat=1000)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="Piano Telemetry", time=0))
    # At 60 BPM with 1000 PPQ, one tick represents one millisecond.
    track.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))

    exported = 0
    skipped = 0
    previous_tick = 0
    with events_path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            raw = payload.get("raw")
            session_time_ns = payload.get("session_time_ns")
            if (
                not isinstance(raw, list)
                or not raw
                or not isinstance(session_time_ns, int)
                or not 0x80 <= raw[0] < 0xF0
            ):
                skipped += 1
                continue

            try:
                message = mido.Message.from_bytes(raw)
            except (TypeError, ValueError):
                skipped += 1
                continue

            absolute_tick = max(0, round(session_time_ns / 1_000_000))
            delta_tick = max(0, absolute_tick - previous_tick)
            previous_tick = max(previous_tick, absolute_tick)
            track.append(message.copy(time=delta_tick))
            exported += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    midi_file.save(output_path)
    return MidiExportResult(
        exported_events=exported,
        skipped_events=skipped,
        output_path=output_path,
    )
