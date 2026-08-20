from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from piano_telemetry.core.config import default_sessions_dir
from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.ports import list_midi_ports
from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig
from piano_telemetry.recorder import SessionRecorder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="piano-telemetry")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="start the local Web portal")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")

    subparsers.add_parser("ports", help="list available MIDI input and output ports")

    route = subparsers.add_parser("route", help="route one MIDI input to one MIDI output")
    route.add_argument("--input", required=True, help="input port index, exact name, or substring")
    route.add_argument("--output", required=True, help="output port index, exact name, or substring")
    route.add_argument("--ingress-capacity", type=int, default=4096)
    route.add_argument("--stats-interval", type=float, default=5.0)
    route.add_argument("--receive-sysex", action="store_true")
    route.add_argument("--receive-clock", action="store_true")
    route.add_argument("--receive-active-sensing", action="store_true")
    route.add_argument("--no-panic-on-stop", action="store_true")
    route.add_argument("--record", action="store_true", help="record one session until shutdown")
    route.add_argument("--sessions-dir", type=Path, default=default_sessions_dir())
    route.add_argument("--piece")
    route.add_argument("--target-bpm", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        raw_args = ["serve"]
    args = build_parser().parse_args(raw_args)
    try:
        if args.command == "serve":
            from piano_telemetry.web_server import run_web_server

            run_web_server(
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
            )
            return 0
        if args.command == "ports":
            return _print_ports()
        if args.command == "route":
            return _run_router(args)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


def _print_ports() -> int:
    ports = list_midi_ports()
    print("MIDI inputs:")
    if ports.inputs:
        for index, name in enumerate(ports.inputs):
            print(f"  [{index}] {name}")
    else:
        print("  (none)")

    print("MIDI outputs:")
    if ports.outputs:
        for index, name in enumerate(ports.outputs):
            print(f"  [{index}] {name}")
    else:
        print("  (none)")
    return 0


def _run_router(args: argparse.Namespace) -> int:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(
        ingress_capacity=args.ingress_capacity
    )
    router = MidiRouter(
        MidiRouterConfig(
            input_port=args.input,
            output_port=args.output,
            receive_sysex=args.receive_sysex,
            receive_clock=args.receive_clock,
            receive_active_sensing=args.receive_active_sensing,
            panic_on_stop=not args.no_panic_on_stop,
        ),
        dispatcher,
    )
    recorder = (
        SessionRecorder(dispatcher, sessions_dir=args.sessions_dir)
        if args.record
        else None
    )

    if recorder is not None:
        recorder.start()
    dispatcher.start()
    try:
        router.start()
        print(f"routing: {router.input_name} -> {router.output_name}")
        if recorder is not None:
            session = recorder.start_session(piece=args.piece, target_bpm=args.target_bpm)
            print(f"recording session: {session.session_id}")
        print("press Ctrl+C to stop")
        while True:
            time.sleep(max(args.stats_interval, 0.1))
            print(
                json.dumps(
                    {
                        "router": router.metrics.snapshot(),
                        "dispatcher": dispatcher.metrics.snapshot(),
                    },
                    ensure_ascii=False,
                )
            )
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        try:
            router.stop()
        finally:
            try:
                if recorder is not None:
                    if recorder.state.value == "recording":
                        result = recorder.stop_session()
                        print(
                            f"session closed: {result.session_id}; "
                            f"events={result.event_count}; complete={result.complete}"
                        )
                    recorder.close()
            finally:
                dispatcher.stop(drain=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
