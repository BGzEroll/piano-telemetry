from __future__ import annotations

from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.analyzer.tonality import (
    DEFAULT_TONALITY,
    normalize_tonality,
    pitch_class_name,
)


_CHORDS: tuple[tuple[str, frozenset[int]], ...] = (
    ("maj7", frozenset((0, 4, 7, 11))),
    ("m7", frozenset((0, 3, 7, 10))),
    ("7", frozenset((0, 4, 7, 10))),
    ("major", frozenset((0, 4, 7))),
    ("minor", frozenset((0, 3, 7))),
    ("dim", frozenset((0, 3, 6))),
    ("aug", frozenset((0, 4, 8))),
    ("sus2", frozenset((0, 2, 7))),
    ("sus4", frozenset((0, 5, 7))),
)


class NoteStateTracker:
    def __init__(self, *, tonality: str = DEFAULT_TONALITY) -> None:
        self._physical: set[tuple[int, int]] = set()
        self._sounding: set[tuple[int, int]] = set()
        self._sustain: dict[int, int] = {}
        self._last_velocity = 0
        self._last_seq: int | None = None
        self._valid = True
        self._tonality = normalize_tonality(tonality)

    def set_tonality(self, tonality: str) -> None:
        self._tonality = normalize_tonality(tonality)

    def reset(self, *, valid: bool = False) -> None:
        self._physical.clear()
        self._sounding.clear()
        self._sustain.clear()
        self._last_velocity = 0
        self._valid = valid

    def apply(self, event: MidiEvent) -> tuple[dict[str, object], tuple[int, int] | None]:
        gap: tuple[int, int] | None = None
        if self._last_seq is not None and event.seq > self._last_seq + 1:
            gap = (self._last_seq + 1, event.seq - 1)
            self.reset(valid=False)
        self._last_seq = event.seq

        channel = event.channel
        if channel is not None:
            if event.type == "note_on" and event.data1 is not None and event.data2:
                key = (channel, event.data1)
                self._physical.add(key)
                self._sounding.add(key)
                self._last_velocity = event.data2
            elif (
                event.type == "note_off"
                or (event.type == "note_on" and event.data2 == 0)
            ) and event.data1 is not None:
                key = (channel, event.data1)
                self._physical.discard(key)
                if self._sustain.get(channel, 0) < 64:
                    self._sounding.discard(key)
            elif event.type == "control_change" and event.data1 is not None:
                self._apply_control_change(channel, event.data1, event.data2 or 0)

        return self.snapshot(), gap

    def snapshot(self) -> dict[str, object]:
        physical_notes = sorted({note for _, note in self._physical})
        sounding_notes = sorted({note for _, note in self._sounding})
        return {
            "kind": "state",
            "seq": self._last_seq,
            "valid": self._valid,
            "physical_notes": physical_notes,
            "sounding_notes": sounding_notes,
            "sustain": max(self._sustain.values(), default=0),
            "last_velocity": self._last_velocity,
            "tonality": self._tonality,
            "chord": _identify_chord(physical_notes, self._tonality),
        }

    def _apply_control_change(self, channel: int, control: int, value: int) -> None:
        if control == 64:
            self._sustain[channel] = value
            if value < 64:
                self._release_unheld(channel)
        elif control in {120, 123}:
            self._clear_channel(channel)
            if control == 120:
                self._sustain[channel] = 0
        elif control == 121:
            self._sustain[channel] = 0
            self._release_unheld(channel)

    def _release_unheld(self, channel: int) -> None:
        self._sounding = {
            key for key in self._sounding if key[0] != channel or key in self._physical
        }

    def _clear_channel(self, channel: int) -> None:
        self._physical = {key for key in self._physical if key[0] != channel}
        self._sounding = {key for key in self._sounding if key[0] != channel}


def _identify_chord(notes: list[int], tonality: str = DEFAULT_TONALITY) -> str | None:
    if len({note % 12 for note in notes}) < 3:
        return None
    pitch_classes = frozenset(note % 12 for note in notes)
    bass = min(notes) % 12
    for root in range(12):
        relative = frozenset((pitch_class - root) % 12 for pitch_class in pitch_classes)
        for suffix, template in _CHORDS:
            if relative != template:
                continue
            root_name = pitch_class_name(root, tonality)
            if suffix == "major":
                name = root_name
            elif suffix == "minor":
                name = f"{root_name}m"
            else:
                name = f"{root_name}{suffix}"
            if bass != root:
                name = f"{name}/{pitch_class_name(bass, tonality)}"
            return name
    return None
