from piano_telemetry.analyzer.note_state import NoteStateTracker
from piano_telemetry.midi.event import MidiEvent


def midi_event(seq: int, raw: list[int]) -> MidiEvent:
    return MidiEvent.from_raw(
        seq=seq,
        captured_monotonic_ns=seq,
        source_port="test",
        raw=raw,
    )


def test_sustain_distinguishes_physical_and_sounding_notes() -> None:
    tracker = NoteStateTracker()
    tracker.apply(midi_event(1, [0x90, 60, 90]))
    tracker.apply(midi_event(2, [0xB0, 64, 100]))
    state, _ = tracker.apply(midi_event(3, [0x80, 60, 0]))

    assert state["physical_notes"] == []
    assert state["sounding_notes"] == [60]

    state, _ = tracker.apply(midi_event(4, [0xB0, 64, 0]))
    assert state["sounding_notes"] == []


def test_chord_and_inversion_are_identified() -> None:
    tracker = NoteStateTracker()
    tracker.apply(midi_event(1, [0x90, 64, 80]))
    tracker.apply(midi_event(2, [0x90, 67, 80]))
    state, _ = tracker.apply(midi_event(3, [0x90, 72, 80]))
    assert state["chord"] == "C/E"


def test_sequence_gap_resets_state_and_marks_it_invalid() -> None:
    tracker = NoteStateTracker()
    tracker.apply(midi_event(1, [0x90, 60, 80]))
    state, gap = tracker.apply(midi_event(4, [0x90, 64, 80]))
    assert gap == (2, 3)
    assert state["valid"] is False
    assert state["physical_notes"] == [64]

