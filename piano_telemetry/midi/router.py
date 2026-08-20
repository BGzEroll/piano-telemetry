from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from time import perf_counter_ns
from typing import Any

from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.core.metrics import RouterMetrics

from .event import MidiEvent
from .ports import _load_rtmidi, resolve_port
from .virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    VirtualMidiDriver,
)


@dataclass(frozen=True, slots=True)
class MidiRouterConfig:
    input_port: str
    output_port: str
    managed_virtual_ports: bool = False
    receive_sysex: bool = False
    receive_clock: bool = False
    receive_active_sensing: bool = False
    panic_on_stop: bool = True


class MidiRouter:
    """Priority MIDI pass-through with isolated best-effort telemetry."""

    def __init__(
        self,
        config: MidiRouterConfig,
        dispatcher: EventDispatcher[MidiEvent],
        *,
        virtual_driver_factory=VirtualMidiDriver,
    ) -> None:
        self.config = config
        self.dispatcher = dispatcher
        self.metrics = RouterMetrics()
        self.input_name: str | None = None
        self.output_name: str | None = None
        self._midi_in: Any | None = None
        self._midi_out: Any | None = None
        self._sequence = count(1)
        self._virtual_driver_factory = virtual_driver_factory

    def start(self) -> None:
        if self._midi_in is not None or self._midi_out is not None:
            raise RuntimeError("MIDI router is already running")

        if self.config.managed_virtual_ports:
            self._start_managed_virtual_ports()
            return

        rtmidi = _load_rtmidi()
        midi_out = rtmidi.MidiOut()
        midi_in = rtmidi.MidiIn()

        output_ports = tuple(midi_out.get_ports())
        input_ports = tuple(midi_in.get_ports())
        output_index = resolve_port(self.config.output_port, output_ports, kind="output")
        input_index = resolve_port(self.config.input_port, input_ports, kind="input")

        self.output_name = output_ports[output_index]
        self.input_name = input_ports[input_index]

        try:
            midi_out.open_port(output_index, "Piano Telemetry Output")
            midi_in.ignore_types(
                sysex=not self.config.receive_sysex,
                timing=not self.config.receive_clock,
                active_sense=not self.config.receive_active_sensing,
            )
            self._midi_out = midi_out
            midi_in.set_callback(self._midi_callback)
            midi_in.open_port(input_index, "Piano Telemetry Input")
            self._midi_in = midi_in
        except Exception:
            try:
                midi_in.cancel_callback()
                midi_in.close_port()
            except Exception:
                pass
            try:
                midi_out.close_port()
            except Exception:
                pass
            self._midi_in = None
            self._midi_out = None
            raise

    def _start_managed_virtual_ports(self) -> None:
        driver = self._virtual_driver_factory()
        midi_out = driver.create_output_port(VIRTUAL_OUTPUT_PORT_NAME)
        self._midi_out = midi_out
        self.output_name = VIRTUAL_OUTPUT_PORT_NAME
        self.input_name = VIRTUAL_INPUT_PORT_NAME
        try:
            midi_in = driver.create_input_port(
                VIRTUAL_INPUT_PORT_NAME,
                self._handle_virtual_message,
            )
        except Exception:
            self._midi_out = None
            self.output_name = None
            self.input_name = None
            midi_out.close_port()
            raise
        self._midi_in = midi_in

    def stop(self) -> None:
        midi_in = self._midi_in
        midi_out = self._midi_out
        self._midi_in = None
        self._midi_out = None

        if midi_in is not None:
            try:
                midi_in.cancel_callback()
            except Exception:
                self.metrics.shutdown_errors_total += 1
            try:
                midi_in.close_port()
            except Exception:
                self.metrics.shutdown_errors_total += 1

        if midi_out is not None:
            try:
                if self.config.panic_on_stop:
                    self._send_panic(midi_out)
            except Exception:
                self.metrics.shutdown_errors_total += 1
            try:
                midi_out.close_port()
            except Exception:
                self.metrics.shutdown_errors_total += 1

    def _midi_callback(self, event: tuple[list[int], float], _: object | None = None) -> None:
        message, _delta_time = event
        self._handle_message(message, captured_monotonic_ns=perf_counter_ns())

    def _handle_virtual_message(self, message: list[int]) -> None:
        if not message:
            return
        status = message[0]
        if status == 0xF0 and not self.config.receive_sysex:
            return
        if status == 0xF8 and not self.config.receive_clock:
            return
        if status == 0xFE and not self.config.receive_active_sensing:
            return
        self._handle_message(message, captured_monotonic_ns=perf_counter_ns())

    def _handle_message(self, message: list[int], *, captured_monotonic_ns: int) -> None:
        """Forward first, then make a best-effort observer publication."""
        self.metrics.events_received_total += 1
        midi_out = self._midi_out
        if midi_out is None:
            self.metrics.forward_errors_total += 1
            return

        try:
            midi_out.send_message(message)
            self.metrics.events_forwarded_total += 1
        except Exception:
            self.metrics.forward_errors_total += 1
            return

        try:
            telemetry_event = MidiEvent.from_raw(
                seq=next(self._sequence),
                captured_monotonic_ns=captured_monotonic_ns,
                source_port=self.input_name or self.config.input_port,
                raw=message,
            )
            self.dispatcher.publish_nowait(telemetry_event)
        except Exception:
            # Telemetry failures are deliberately isolated from MIDI output.
            self.metrics.observer_publish_errors_total += 1

    @staticmethod
    def _send_panic(midi_out: Any) -> None:
        for channel in range(16):
            status = 0xB0 | channel
            midi_out.send_message([status, 64, 0])
            midi_out.send_message([status, 123, 0])
            midi_out.send_message([status, 120, 0])
