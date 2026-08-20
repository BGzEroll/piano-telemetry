"""Measure the managed virtual MIDI route with a local round-trip probe.

The probe sends one short MIDI message to ``Piano Telemetry Input`` and
timestamps the matching callback from ``Piano Telemetry Output``.  Only one
message is in flight at a time, so the result represents latency rather than
queueing throughput.

Run from the project root in the piano-midi environment::

    python tests/benchmark_midi_latency.py

If the Web UI or CLI already owns the managed ports, use::

    python tests/benchmark_midi_latency.py --existing-router
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
from dataclasses import asdict, dataclass
from queue import Empty, Queue
from time import monotonic, perf_counter, perf_counter_ns, sleep
from typing import Iterable

import rtmidi

from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    virtual_midi_status,
)


@dataclass(frozen=True, slots=True)
class LatencyResult:
    samples_requested: int
    samples_received: int
    timeouts: int
    minimum_ms: float
    median_ms: float
    mean_ms: float
    p95_ms: float
    p99_ms: float
    maximum_ms: float
    standard_deviation_ms: float
    elapsed_seconds: float
    samples_per_second: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Piano Telemetry's managed virtual MIDI route."
    )
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="maximum seconds to wait for each returned message",
    )
    parser.add_argument(
        "--interval-ms",
        type=float,
        default=0.0,
        help="optional pause after each sample",
    )
    parser.add_argument(
        "--existing-router",
        action="store_true",
        help="connect to ports already owned by another Piano Telemetry process",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON",
    )
    parser.add_argument(
        "--max-p99-ms",
        type=float,
        help="return a non-zero exit code if P99 exceeds this value",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.samples < 1:
        raise ValueError("--samples must be at least 1")
    if args.warmup < 0:
        raise ValueError("--warmup cannot be negative")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    if args.interval_ms < 0:
        raise ValueError("--interval-ms cannot be negative")
    if args.max_p99_ms is not None and args.max_p99_ms <= 0:
        raise ValueError("--max-p99-ms must be greater than zero")


def resolve_unique_port(names: Iterable[str], target: str, *, kind: str) -> tuple[int, str]:
    ports = tuple(names)
    folded_target = target.casefold()
    exact = [
        (index, name)
        for index, name in enumerate(ports)
        if name.casefold() == folded_target
    ]
    if len(exact) == 1:
        return exact[0]

    partial = [
        (index, name)
        for index, name in enumerate(ports)
        if folded_target in name.casefold()
    ]
    if len(partial) == 1:
        return partial[0]

    available = ", ".join(repr(name) for name in ports) or "(none)"
    if not partial:
        raise RuntimeError(f"{kind} port {target!r} not found; available: {available}")
    matches = ", ".join(repr(name) for _, name in partial)
    raise RuntimeError(f"{kind} port {target!r} is ambiguous; matches: {matches}")


def wait_for_port(
    midi_port: rtmidi.MidiIn | rtmidi.MidiOut,
    target: str,
    *,
    kind: str,
    timeout: float = 5.0,
) -> tuple[int, str]:
    deadline = monotonic() + timeout
    last_error: RuntimeError | None = None
    while monotonic() < deadline:
        try:
            return resolve_unique_port(midi_port.get_ports(), target, kind=kind)
        except RuntimeError as exc:
            last_error = exc
            sleep(0.05)
    assert last_error is not None
    raise last_error


class RoundTripProbe:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self._received: Queue[tuple[tuple[int, ...], int]] = Queue()
        self._midi_in = rtmidi.MidiIn()
        self._midi_out = rtmidi.MidiOut()
        self.input_name: str | None = None
        self.output_name: str | None = None

    def open(self) -> None:
        # From the client perspective, the middleware input is an output port,
        # while the middleware output is an input port.
        output_index, self.output_name = wait_for_port(
            self._midi_out,
            VIRTUAL_INPUT_PORT_NAME,
            kind="client output",
        )
        input_index, self.input_name = wait_for_port(
            self._midi_in,
            VIRTUAL_OUTPUT_PORT_NAME,
            kind="client input",
        )
        self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        self._midi_in.set_callback(self._on_message)
        self._midi_in.open_port(input_index, "Piano Telemetry Latency Receiver")
        self._midi_out.open_port(output_index, "Piano Telemetry Latency Sender")

    def close(self) -> None:
        try:
            self._midi_in.cancel_callback()
        except Exception:
            pass
        if self._midi_out.is_port_open():
            self._midi_out.close_port()
        if self._midi_in.is_port_open():
            self._midi_in.close_port()

    def measure_one(self, sequence: int) -> float | None:
        self._discard_received()
        # Controller 119 on channel 16 is reserved here for the probe.  With
        # one message in flight, the 7-bit value is sufficient for matching.
        expected = (0xBF, 119, sequence & 0x7F)
        started_ns = perf_counter_ns()
        self._midi_out.send_message(list(expected))
        deadline = monotonic() + self.timeout

        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            try:
                message, received_ns = self._received.get(timeout=remaining)
            except Empty:
                return None
            if message == expected:
                return (received_ns - started_ns) / 1_000_000

    def _on_message(
        self,
        event: tuple[list[int], float],
        _data: object | None = None,
    ) -> None:
        message, _delta_time = event
        self._received.put_nowait((tuple(message), perf_counter_ns()))

    def _discard_received(self) -> None:
        while True:
            try:
                self._received.get_nowait()
            except Empty:
                return


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def summarize(
    latencies_ms: list[float],
    *,
    requested: int,
    elapsed_seconds: float,
) -> LatencyResult:
    if not latencies_ms:
        raise RuntimeError("no MIDI messages completed the round trip")
    return LatencyResult(
        samples_requested=requested,
        samples_received=len(latencies_ms),
        timeouts=requested - len(latencies_ms),
        minimum_ms=min(latencies_ms),
        median_ms=statistics.median(latencies_ms),
        mean_ms=statistics.fmean(latencies_ms),
        p95_ms=percentile(latencies_ms, 0.95),
        p99_ms=percentile(latencies_ms, 0.99),
        maximum_ms=max(latencies_ms),
        standard_deviation_ms=(
            statistics.pstdev(latencies_ms) if len(latencies_ms) > 1 else 0.0
        ),
        elapsed_seconds=elapsed_seconds,
        samples_per_second=len(latencies_ms) / elapsed_seconds,
    )


def print_human_result(
    result: LatencyResult,
    *,
    warmup: int,
    input_name: str | None,
    output_name: str | None,
    router_metrics: dict[str, int] | None,
) -> None:
    print("Piano Telemetry MIDI latency benchmark")
    print(f"  Platform: {platform.platform()} / Python {platform.python_version()}")
    print(f"  Route:    {output_name} -> middleware -> {input_name}")
    print(f"  Samples:  {result.samples_received}/{result.samples_requested} (+ {warmup} warmup)")
    print(f"  Timeouts: {result.timeouts}")
    print()
    print(f"  min      {result.minimum_ms:9.3f} ms")
    print(f"  median   {result.median_ms:9.3f} ms")
    print(f"  mean     {result.mean_ms:9.3f} ms")
    print(f"  P95      {result.p95_ms:9.3f} ms")
    print(f"  P99      {result.p99_ms:9.3f} ms")
    print(f"  max      {result.maximum_ms:9.3f} ms")
    print(f"  stddev   {result.standard_deviation_ms:9.3f} ms")
    print(f"  rate     {result.samples_per_second:9.1f} samples/s")
    if router_metrics is not None:
        print(f"  router   {router_metrics}")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    dispatcher: EventDispatcher[MidiEvent] | None = None
    router: MidiRouter | None = None
    probe: RoundTripProbe | None = None

    try:
        if not args.existing_router:
            driver_status = virtual_midi_status()
            if not driver_status.available:
                raise RuntimeError(driver_status.message)
            dispatcher = EventDispatcher(ingress_capacity=4096)
            dispatcher.start()
            router = MidiRouter(
                MidiRouterConfig(
                    input_port=VIRTUAL_INPUT_PORT_NAME,
                    output_port=VIRTUAL_OUTPUT_PORT_NAME,
                    managed_virtual_ports=True,
                    panic_on_stop=False,
                ),
                dispatcher,
            )
            router.start()

        probe = RoundTripProbe(timeout=args.timeout)
        probe.open()

        for sequence in range(args.warmup):
            latency = probe.measure_one(sequence)
            if latency is None:
                raise RuntimeError("warmup message timed out")

        latencies_ms: list[float] = []
        started = perf_counter()
        for sequence in range(args.samples):
            latency = probe.measure_one(args.warmup + sequence)
            if latency is not None:
                latencies_ms.append(latency)
            if args.interval_ms:
                sleep(args.interval_ms / 1000)
        elapsed = perf_counter() - started

        result = summarize(
            latencies_ms,
            requested=args.samples,
            elapsed_seconds=elapsed,
        )
        router_metrics = router.metrics.snapshot() if router is not None else None
        if args.json:
            payload = asdict(result)
            payload["warmup"] = args.warmup
            payload["router_metrics"] = router_metrics
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_human_result(
                result,
                warmup=args.warmup,
                input_name=probe.input_name,
                output_name=probe.output_name,
                router_metrics=router_metrics,
            )

        if result.timeouts:
            return 1
        if args.max_p99_ms is not None and result.p99_ms > args.max_p99_ms:
            return 1
        return 0
    except KeyboardInterrupt:
        print("benchmark interrupted", file=sys.stderr)
        return 130
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if not args.existing_router:
            print(
                "If Piano Telemetry already owns the ports, rerun with --existing-router.",
                file=sys.stderr,
            )
        return 2
    finally:
        if probe is not None:
            probe.close()
        if router is not None:
            router.stop()
        if dispatcher is not None:
            dispatcher.stop(drain=True)


if __name__ == "__main__":
    raise SystemExit(main())
