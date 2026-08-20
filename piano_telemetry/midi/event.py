from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_CHANNEL_MESSAGE_TYPES = {
    0x80: "note_off",
    0x90: "note_on",
    0xA0: "poly_aftertouch",
    0xB0: "control_change",
    0xC0: "program_change",
    0xD0: "channel_aftertouch",
    0xE0: "pitchwheel",
}

_SYSTEM_MESSAGE_TYPES = {
    0xF0: "sysex",
    0xF1: "quarter_frame",
    0xF2: "song_position",
    0xF3: "song_select",
    0xF6: "tune_request",
    0xF7: "sysex_end",
    0xF8: "clock",
    0xFA: "start",
    0xFB: "continue",
    0xFC: "stop",
    0xFE: "active_sensing",
    0xFF: "system_reset",
}


@dataclass(frozen=True, slots=True)
class MidiEvent:
    """Immutable canonical event shared by all telemetry subscribers."""

    seq: int
    captured_monotonic_ns: int
    source_port: str
    raw: tuple[int, ...]
    type: str
    channel: int | None = None
    session_time_ns: int | None = None
    data1: int | None = None
    data2: int | None = None
    schema_version: int = 1
    kind: str = "midi_event"

    @classmethod
    def from_raw(
        cls,
        *,
        seq: int,
        captured_monotonic_ns: int,
        source_port: str,
        raw: list[int] | tuple[int, ...],
        session_time_ns: int | None = None,
    ) -> "MidiEvent":
        normalized = tuple(int(value) & 0xFF for value in raw)
        if not normalized:
            raise ValueError("MIDI message cannot be empty")

        status = normalized[0]
        if status < 0x80:
            message_type = "invalid"
            channel = None
        elif status < 0xF0:
            message_type = _CHANNEL_MESSAGE_TYPES.get(status & 0xF0, "unknown")
            channel = status & 0x0F
        else:
            message_type = _SYSTEM_MESSAGE_TYPES.get(status, "system_unknown")
            channel = None

        return cls(
            seq=seq,
            captured_monotonic_ns=captured_monotonic_ns,
            source_port=source_port,
            raw=normalized,
            type=message_type,
            channel=channel,
            session_time_ns=session_time_ns,
            data1=normalized[1] if len(normalized) > 1 else None,
            data2=normalized[2] if len(normalized) > 2 else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "seq": self.seq,
            "captured_monotonic_ns": self.captured_monotonic_ns,
            "source_port": self.source_port,
            "raw": list(self.raw),
            "type": self.type,
        }
        if self.session_time_ns is not None:
            payload["session_time_ns"] = self.session_time_ns
        if self.channel is not None:
            payload["channel"] = self.channel

        if self.type in {"note_on", "note_off", "poly_aftertouch"}:
            payload["note"] = self.data1
            if self.type in {"note_on", "note_off"}:
                payload["velocity"] = self.data2
            else:
                payload["pressure"] = self.data2
        elif self.type == "control_change":
            payload["control"] = self.data1
            payload["value"] = self.data2
        elif self.type == "program_change":
            payload["program"] = self.data1
        elif self.type == "channel_aftertouch":
            payload["pressure"] = self.data1
        elif self.type == "pitchwheel" and self.data1 is not None and self.data2 is not None:
            payload["pitch"] = ((self.data2 << 7) | self.data1) - 8192
        else:
            if self.data1 is not None:
                payload["data1"] = self.data1
            if self.data2 is not None:
                payload["data2"] = self.data2
        return payload

