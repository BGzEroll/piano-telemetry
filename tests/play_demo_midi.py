"""向 loopMIDI 输出一段原创钢琴 MIDI，用于联调 NanoHost。

推荐从项目根目录运行：
    python tests/play_demo_midi.py

脚本默认选择名称中唯一包含 ``test`` 的 MIDI 输出端口。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Iterable

import rtmidi


@dataclass(frozen=True, slots=True)
class Event:
    beat: float
    order: int
    message: tuple[int, ...]


# 原创短曲《窗边晨光》，C 大调，16 个四拍小节加一个六拍尾声。
CHORDS = (
    (36, (48, 52, 55)),  # C
    (33, (45, 48, 52)),  # Am
    (41, (48, 53, 57)),  # F
    (43, (50, 55, 59)),  # G
    (40, (47, 52, 55)),  # Em
    (33, (45, 48, 52)),  # Am
    (38, (45, 50, 53)),  # Dm
    (43, (50, 55, 59)),  # G
    (36, (48, 52, 55)),  # C
    (43, (50, 55, 59)),  # G
    (33, (45, 48, 52)),  # Am
    (40, (47, 52, 55)),  # Em
    (41, (48, 53, 57)),  # F
    (40, (48, 52, 55)),  # C/E
    (38, (45, 50, 53)),  # Dm
    (43, (50, 55, 59)),  # G
    (36, (48, 52, 55, 60)),  # C 尾声
)

MELODY = (
    ((0, 1, 76), (1, 1, 79), (2, 2, 81)),
    ((0, 1, 79), (1, 1, 76), (2, 2, 72)),
    ((0, .5, 72), (.5, .5, 74), (1, 1, 76), (2, 1, 79), (3, 1, 81)),
    ((0, 2, 83), (2, 1, 79), (3, 1, 74)),
    ((0, 1, 76), (1, 1, 79), (2, .5, 83), (2.5, .5, 81), (3, 1, 79)),
    ((0, 1, 81), (1, 1, 84), (2, 1, 83), (3, 1, 81)),
    ((0, 1, 77), (1, 1, 76), (2, 1, 74), (3, 1, 72)),
    ((0, .5, 74), (.5, .5, 76), (1, 1, 79), (2, 2, 83)),
    ((0, 1, 84), (1, 1, 83), (2, 1, 79), (3, 1, 76)),
    ((0, 1, 79), (1, 1, 74), (2, 2, 71)),
    ((0, .5, 72), (.5, .5, 74), (1, 1, 76), (2, 1, 81), (3, 1, 79)),
    ((0, 2, 76), (2, 1, 74), (3, 1, 71)),
    ((0, 1, 72), (1, 1, 77), (2, 1, 81), (3, 1, 84)),
    ((0, 1, 83), (1, 1, 79), (2, 2, 76)),
    ((0, 1, 74), (1, 1, 77), (2, 1, 76), (3, 1, 74)),
    ((0, .5, 74), (.5, .5, 76), (1, 1, 79), (2, 2, 83)),
    ((0, 1, 84), (1, 1, 83), (2, 4, 84)),
)

BAR_LENGTHS = (4,) * 16 + (6,)


def add_note(
    events: list[Event],
    *,
    beat: float,
    duration: float,
    note: int,
    velocity: int,
    channel: int,
) -> None:
    events.append(Event(beat, 2, (0x90 | channel, note, velocity)))
    events.append(Event(beat + duration, 0, (0x80 | channel, note, 0)))


def build_song(channel: int, sustain: bool) -> tuple[list[Event], float]:
    events: list[Event] = []
    bar_start = 0.0

    for index, ((bass, chord), melody, bar_length) in enumerate(
        zip(CHORDS, MELODY, BAR_LENGTHS, strict=True)
    ):
        is_final = index == len(CHORDS) - 1
        if sustain:
            events.append(Event(bar_start, 1, (0xB0 | channel, 64, 72)))
            events.append(Event(bar_start + bar_length - .1, 0, (0xB0 | channel, 64, 0)))

        if is_final:
            add_note(events, beat=bar_start, duration=5.8, note=bass, velocity=64, channel=channel)
            for chord_note in chord:
                add_note(
                    events,
                    beat=bar_start,
                    duration=5.8,
                    note=chord_note,
                    velocity=58,
                    channel=channel,
                )
        else:
            add_note(events, beat=bar_start, duration=1.8, note=bass, velocity=58, channel=channel)
            add_note(events, beat=bar_start + 2, duration=1.8, note=bass, velocity=54, channel=channel)
            for chord_beat, velocity in ((0, 52), (2, 48)):
                for chord_note in chord:
                    add_note(
                        events,
                        beat=bar_start + chord_beat,
                        duration=1.6,
                        note=chord_note,
                        velocity=velocity,
                        channel=channel,
                    )

        for offset, duration, note in melody:
            phrase_shape = (0, 4, 8, 2)[index % 4]
            velocity = min(104, 78 + phrase_shape + (note % 3) * 3)
            add_note(
                events,
                beat=bar_start + offset,
                duration=max(.15, duration - .08),
                note=note,
                velocity=velocity,
                channel=channel,
            )
        bar_start += bar_length

    events.sort(key=lambda event: (event.beat, event.order, event.message[1:]))
    return events, bar_start


def resolve_output(selector: str, ports: Iterable[str]) -> tuple[int, str]:
    names = tuple(ports)
    if not names:
        raise RuntimeError("没有发现 MIDI 输出端口，请先启动 loopMIDI 并创建 test 端口")

    try:
        index = int(selector)
    except ValueError:
        index = -1
    if 0 <= index < len(names):
        return index, names[index]

    folded = selector.casefold()
    exact = [(index, name) for index, name in enumerate(names) if name.casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    partial = [(index, name) for index, name in enumerate(names) if folded in name.casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise RuntimeError(f"找不到 MIDI 输出端口：{selector!r}")
    matches = "、".join(f"[{index}] {name}" for index, name in partial)
    raise RuntimeError(f"端口名称匹配到多个结果，请用编号或完整名称指定：{matches}")


def wait_until(target: float) -> None:
    while True:
        remaining = target - perf_counter()
        if remaining <= 0:
            return
        sleep(min(remaining, .02))


def play(
    midi_out: rtmidi.MidiOut,
    events: list[Event],
    *,
    bpm: float,
    channel: int,
    total_beats: float,
) -> None:
    seconds_per_beat = 60.0 / bpm
    start = perf_counter() + .15
    next_bar = 1

    midi_out.send_message([0xC0 | channel, 0])  # GM Acoustic Grand Piano
    midi_out.send_message([0xB0 | channel, 7, 100])  # Channel volume
    midi_out.send_message([0xB0 | channel, 11, 112])  # Expression

    for event in events:
        wait_until(start + event.beat * seconds_per_beat)
        midi_out.send_message(list(event.message))
        current_bar = min(17, int(event.beat // 4) + 1)
        if current_bar > next_bar:
            next_bar = current_bar
            print(f"  播放进度：第 {current_bar}/17 小节", flush=True)

    wait_until(start + total_beats * seconds_per_beat)


def panic(midi_out: rtmidi.MidiOut, channel: int) -> None:
    for message in (
        [0xB0 | channel, 64, 0],
        [0xB0 | channel, 123, 0],
        [0xB0 | channel, 120, 0],
    ):
        try:
            midi_out.send_message(message)
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="向 loopMIDI 播放原创钢琴短曲《窗边晨光》"
    )
    parser.add_argument("--port", default="test", help="输出端口编号、完整名称或唯一片段")
    parser.add_argument("--bpm", type=float, default=108, help="速度，默认 108 BPM")
    parser.add_argument("--channel", type=int, default=1, choices=range(1, 17), help="MIDI 通道 1-16")
    parser.add_argument("--repeat", type=int, default=1, help="重复次数")
    parser.add_argument("--no-sustain", action="store_true", help="不发送延音踏板消息")
    parser.add_argument("--list-ports", action="store_true", help="仅列出输出端口")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 30 <= args.bpm <= 300:
        raise SystemExit("--bpm 必须在 30 到 300 之间")
    if args.repeat < 1:
        raise SystemExit("--repeat 必须大于等于 1")

    midi_out = rtmidi.MidiOut()
    ports = tuple(midi_out.get_ports())
    if args.list_ports:
        print("MIDI 输出端口：")
        for index, name in enumerate(ports):
            print(f"  [{index}] {name}")
        return 0

    channel = args.channel - 1
    try:
        port_index, port_name = resolve_output(args.port, ports)
        midi_out.open_port(port_index, "Piano Telemetry Demo Player")
        events, total_beats = build_song(channel, sustain=not args.no_sustain)
        duration = total_beats * 60 / args.bpm
        print(f"输出端口：{port_name}")
        print(f"曲目：原创短曲《窗边晨光》 · {args.bpm:g} BPM · 约 {duration:.0f} 秒")
        print("开始播放，请确认 NanoHost 音量适中。按 Ctrl+C 可随时停止。", flush=True)
        for repeat_index in range(args.repeat):
            if args.repeat > 1:
                print(f"第 {repeat_index + 1}/{args.repeat} 遍", flush=True)
            play(
                midi_out,
                events,
                bpm=args.bpm,
                channel=channel,
                total_beats=total_beats,
            )
        print("播放完成。")
        return 0
    except KeyboardInterrupt:
        print("\n已停止播放。")
        return 130
    except RuntimeError as exc:
        print(f"错误：{exc}")
        print("可运行 python tests/play_demo_midi.py --list-ports 查看端口。")
        return 1
    finally:
        panic(midi_out, channel)
        if midi_out.is_port_open():
            midi_out.close_port()


if __name__ == "__main__":
    raise SystemExit(main())
