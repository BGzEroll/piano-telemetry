from piano_telemetry.midi.event import MidiEvent


def test_note_event_is_parsed_and_serialized() -> None:
    event = MidiEvent.from_raw(
        seq=7,
        captured_monotonic_ns=123,
        source_port="piano",
        raw=[0x92, 64, 81],
    )

    assert event.type == "note_on"
    assert event.channel == 2
    assert event.raw == (0x92, 64, 81)
    assert event.to_dict()["note"] == 64
    assert event.to_dict()["velocity"] == 81


def test_pitchwheel_is_converted_to_signed_value() -> None:
    center = MidiEvent.from_raw(
        seq=1,
        captured_monotonic_ns=1,
        source_port="piano",
        raw=[0xE0, 0, 64],
    )
    assert center.to_dict()["pitch"] == 0


def test_system_message_has_no_channel() -> None:
    event = MidiEvent.from_raw(
        seq=1,
        captured_monotonic_ns=1,
        source_port="piano",
        raw=[0xF8],
    )
    assert event.type == "clock"
    assert event.channel is None

