"""向 Piano Telemetry 播放原创日系钢琴编配测试曲。

推荐从项目根目录运行：

    python tests/play_demo_midi.py

曲目使用宽音域分解和弦、延音、力度渐强、快速经过句和高潮八度旋律，
用于同时检查 MIDI 路由、NanoHost、瀑布流、键盘及谱表显示。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Iterable

import rtmidi

from generate_airborne_piano_demo import BAR_COUNT, BPM, build_events


DEFAULT_OUTPUT_PORT = "Piano Telemetry Input"


@dataclass(frozen=True, slots=True)
class Event:
    beat: float
    order: int
    message: tuple[int, ...]


def build_song(channel: int, sustain: bool) -> tuple[list[Event], float]:
    scheduled, total_beats = build_events()
    events: list[Event] = []
    for item in scheduled:
        message = item.message.copy(channel=channel)
        if not sustain and message.type == "control_change" and message.control == 64:
            continue
        events.append(Event(item.beat, item.order, tuple(message.bytes())))
    return events, total_beats


def resolve_output(selector: str, ports: Iterable[str]) -> tuple[int, str]:
    names = tuple(ports)
    if not names:
        raise RuntimeError("没有发现 MIDI 输出端口，请先在网页设置中启动 MIDI 路由")

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
        sleep(min(remaining, 0.02))


def play(
    midi_out: rtmidi.MidiOut,
    events: list[Event],
    *,
    bpm: float,
    channel: int,
    total_beats: float,
) -> None:
    seconds_per_beat = 60.0 / bpm
    start = perf_counter() + 0.15
    next_bar = 1

    midi_out.send_message([0xC0 | channel, 0])  # GM Acoustic Grand Piano
    midi_out.send_message([0xB0 | channel, 7, 104])  # Channel volume
    midi_out.send_message([0xB0 | channel, 11, 112])  # Expression

    for event in events:
        wait_until(start + event.beat * seconds_per_beat)
        midi_out.send_message(list(event.message))
        current_bar = min(BAR_COUNT, int(event.beat // 4) + 1)
        if current_bar > next_bar:
            next_bar = current_bar
            print(f"  播放进度：第 {current_bar}/{BAR_COUNT} 小节", flush=True)

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
        description="向 Piano Telemetry Input 播放原创测试曲《凌空之歌》"
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_OUTPUT_PORT,
        help="输出端口编号、完整名称或唯一片段",
    )
    parser.add_argument("--bpm", type=float, default=BPM, help=f"速度，默认 {BPM} BPM")
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
        print(
            f"曲目：原创测试曲《凌空之歌》 · {args.bpm:g} BPM · "
            f"{BAR_COUNT} 小节 · 约 {duration:.0f} 秒"
        )
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
