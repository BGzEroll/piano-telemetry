"""Generate the original MIDI asset used by ``play_demo_midi.py``.

The composition uses broad traits common to dramatic Japanese piano
arrangements—wide arpeggios, a singing upper melody, octave reinforcement and
a layered climax—without reproducing a particular song or arrangement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mido


OUTPUT_PATH = Path(__file__).parent / "assets" / "airborne_piano_demo.mid"
TICKS_PER_BEAT = 480
BPM = 126


@dataclass(frozen=True, slots=True)
class ScheduledMessage:
    beat: float
    order: int
    message: mido.Message


# Bass note plus a four-note voicing. The progression is intentionally generic
# and supports a continuous, airborne character rather than quoting a theme.
CHORDS = (
    (38, (50, 54, 57, 62)),  # D
    (37, (49, 52, 57, 61)),  # A/C#
    (35, (47, 50, 54, 59)),  # Bm
    (31, (43, 47, 50, 55)),  # G
    (42, (50, 54, 57, 62)),  # D/F#
    (33, (45, 49, 52, 57)),  # A
    (40, (47, 52, 55, 59)),  # Em7
    (33, (45, 49, 52, 57)),  # A
    (35, (47, 50, 54, 59)),  # Bm
    (31, (43, 47, 50, 55)),  # G
    (38, (50, 54, 57, 62)),  # D
    (33, (45, 49, 52, 57)),  # A
    (35, (47, 50, 54, 59)),  # Bm
    (31, (43, 47, 50, 55)),  # G
    (40, (47, 52, 55, 59)),  # Em7
    (33, (45, 49, 52, 57)),  # A
    (38, (50, 54, 57, 62)),  # D
    (37, (49, 52, 57, 61)),  # A/C#
    (35, (47, 50, 54, 59)),  # Bm
    (31, (43, 47, 50, 55)),  # G
    (40, (47, 52, 55, 59)),  # Em7
    (33, (45, 49, 52, 57)),  # A
    (38, (50, 54, 57, 62)),  # D
    (38, (50, 54, 57, 62)),  # D coda
)


# (offset, duration, MIDI pitch), one four-beat phrase per bar. This melody is
# original and deliberately favors long, legato arcs over a song quotation.
MELODY = (
    ((0.0, 1.0, 78), (1.0, 1.0, 81), (2.0, 2.0, 86)),
    ((0.0, 0.5, 85), (0.5, 0.5, 83), (1.0, 1.0, 81), (2.0, 2.0, 76)),
    ((0.0, 1.0, 78), (1.0, 0.5, 76), (1.5, 0.5, 74), (2.0, 1.0, 71), (3.0, 1.0, 74)),
    ((0.0, 2.0, 79), (2.0, 1.0, 81), (3.0, 1.0, 83)),
    ((0.0, 1.0, 86), (1.0, 1.0, 85), (2.0, 1.0, 81), (3.0, 1.0, 78)),
    ((0.0, 0.5, 76), (0.5, 0.5, 78), (1.0, 1.0, 81), (2.0, 2.0, 85)),
    ((0.0, 1.0, 83), (1.0, 1.0, 81), (2.0, 0.5, 79), (2.5, 0.5, 78), (3.0, 1.0, 76)),
    ((0.0, 1.5, 78), (1.5, 0.5, 81), (2.0, 2.0, 85)),
    ((0.0, 0.5, 86), (0.5, 0.5, 88), (1.0, 1.0, 90), (2.0, 1.0, 86), (3.0, 1.0, 83)),
    ((0.0, 1.0, 81), (1.0, 1.0, 79), (2.0, 2.0, 83)),
    ((0.0, 1.0, 86), (1.0, 0.5, 85), (1.5, 0.5, 83), (2.0, 1.0, 81), (3.0, 1.0, 78)),
    ((0.0, 2.0, 76), (2.0, 1.0, 78), (3.0, 1.0, 81)),
    ((0.0, 1.0, 83), (1.0, 1.0, 86), (2.0, 2.0, 90)),
    ((0.0, 0.5, 88), (0.5, 0.5, 86), (1.0, 1.0, 83), (2.0, 2.0, 79)),
    ((0.0, 1.0, 81), (1.0, 0.5, 79), (1.5, 0.5, 78), (2.0, 1.0, 76), (3.0, 1.0, 74)),
    ((0.0, 0.5, 76), (0.5, 0.5, 78), (1.0, 1.0, 81), (2.0, 1.0, 85), (3.0, 1.0, 88)),
    ((0.0, 1.0, 90), (1.0, 1.0, 88), (2.0, 1.0, 86), (3.0, 1.0, 93)),
    ((0.0, 0.5, 92), (0.5, 0.5, 90), (1.0, 1.0, 88), (2.0, 2.0, 85)),
    ((0.0, 1.0, 86), (1.0, 0.5, 83), (1.5, 0.5, 81), (2.0, 1.0, 83), (3.0, 1.0, 86)),
    ((0.0, 2.0, 91), (2.0, 1.0, 90), (3.0, 1.0, 88)),
    ((0.0, 0.5, 86), (0.5, 0.5, 88), (1.0, 1.0, 90), (2.0, 1.0, 93), (3.0, 1.0, 95)),
    ((0.0, 1.0, 93), (1.0, 1.0, 90), (2.0, 1.0, 88), (3.0, 1.0, 85)),
    ((0.0, 1.0, 86), (1.0, 1.0, 90), (2.0, 2.0, 93)),
    ((0.0, 1.0, 90), (1.0, 1.0, 86), (2.0, 4.0, 98)),
)

BAR_COUNT = len(CHORDS)


def add_note(
    events: list[ScheduledMessage],
    beat: float,
    duration: float,
    pitch: int,
    velocity: int,
) -> None:
    events.append(ScheduledMessage(beat, 2, mido.Message("note_on", note=pitch, velocity=velocity)))
    events.append(
        ScheduledMessage(beat + duration, 0, mido.Message("note_off", note=pitch, velocity=0))
    )


def build_events() -> tuple[list[ScheduledMessage], float]:
    events: list[ScheduledMessage] = []
    arpeggio_pattern = (0, 1, 2, 1, 3, 2, 1, 2)

    for bar, ((bass, chord), melody) in enumerate(zip(CHORDS, MELODY, strict=True)):
        start = bar * 4.0
        climax = bar >= 16
        final = bar == len(CHORDS) - 1
        base_velocity = 48 + min(bar, 16) * 2

        events.append(
            ScheduledMessage(start, 1, mido.Message("control_change", control=64, value=76))
        )
        events.append(
            ScheduledMessage(
                start + (5.85 if final else 3.86),
                0,
                mido.Message("control_change", control=64, value=0),
            )
        )

        if final:
            add_note(events, start, 5.8, bass, 82)
            add_note(events, start, 5.8, bass + 12, 76)
            for index, pitch in enumerate((62, 66, 69, 74, 78, 81, 86)):
                add_note(events, start + index * 0.06, 5.7 - index * 0.06, pitch, 74 + index * 3)
        else:
            # Wide bass anchors make the low end visible without becoming a wall.
            for offset in (0.0, 2.0):
                add_note(events, start + offset, 1.75, bass, base_velocity + 4)
                if climax:
                    add_note(events, start + offset, 1.65, bass + 12, base_velocity)

            for step, chord_index in enumerate(arpeggio_pattern):
                pitch = chord[chord_index] + (12 if step >= 4 else 0)
                add_note(
                    events,
                    start + step * 0.5,
                    0.46,
                    pitch,
                    base_velocity + (step % 4) * 3,
                )

        for offset, duration, pitch in melody:
            melody_velocity = min(116, base_velocity + 28 + (pitch % 4) * 2)
            add_note(events, start + offset, max(0.18, duration - 0.06), pitch, melody_velocity)
            if climax and not final:
                add_note(
                    events,
                    start + offset,
                    max(0.18, duration - 0.08),
                    pitch - 12,
                    melody_velocity - 13,
                )

        # A short upward flourish at phrase boundaries exercises fast notes.
        if bar in {7, 15, 21}:
            scale = (74, 76, 78, 79, 81, 83, 85, 86)
            for index, pitch in enumerate(scale):
                add_note(events, start + 3.0 + index * 0.125, 0.115, pitch, 66 + index * 3)

    total_beats = (len(CHORDS) - 1) * 4.0 + 6.0
    events.sort(key=lambda item: (item.beat, item.order, item.message.bytes()))
    return events, total_beats


def write_midi(path: Path) -> None:
    midi_file = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    meta = mido.MidiTrack()
    piano = mido.MidiTrack()
    midi_file.tracks.extend((meta, piano))

    meta.append(mido.MetaMessage("track_name", name="Airborne Piano Demo"))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    meta.append(mido.MetaMessage("key_signature", key="D"))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))

    piano.append(mido.MetaMessage("track_name", name="Acoustic Grand Piano"))
    piano.append(mido.Message("program_change", program=0, time=0))
    piano.append(mido.Message("control_change", control=7, value=104, time=0))
    piano.append(mido.Message("control_change", control=11, value=112, time=0))

    events, total_beats = build_events()
    previous_tick = 0
    for event in events:
        tick = round(event.beat * TICKS_PER_BEAT)
        message = event.message.copy(time=tick - previous_tick)
        piano.append(message)
        previous_tick = tick
    end_tick = round(total_beats * TICKS_PER_BEAT)
    piano.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - previous_tick)))

    path.parent.mkdir(parents=True, exist_ok=True)
    midi_file.save(path)


def main() -> int:
    write_midi(OUTPUT_PATH)
    print(f"已生成：{OUTPUT_PATH.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
