from __future__ import annotations

import piano_telemetry.midi.router as router_module

from piano_telemetry.core.config import AppSettings
from piano_telemetry.core.controller import MidiController
from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    VirtualMidiStatus,
)


class RecordingDispatcher:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def publish_nowait(self, event: MidiEvent) -> bool:
        self.calls.append(("publish", event.raw))
        return True


class FakeInputPort:
    def __init__(self, callback, calls: list[tuple[str, object]]) -> None:
        self.callback = callback
        self.calls = calls

    def cancel_callback(self) -> None:
        self.calls.append(("cancel_input", None))

    def close_port(self) -> None:
        self.calls.append(("close_input", None))


class FakeOutputPort:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def send_message(self, message) -> None:
        self.calls.append(("send", tuple(message)))

    def close_port(self) -> None:
        self.calls.append(("close_output", None))


class FakeVirtualDriver:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls
        self.input: FakeInputPort | None = None

    def create_output_port(self, name: str) -> FakeOutputPort:
        self.calls.append(("create_output", name))
        return FakeOutputPort(self.calls)

    def create_input_port(self, name: str, callback) -> FakeInputPort:
        self.calls.append(("create_input", name))
        self.input = FakeInputPort(callback, self.calls)
        return self.input


class FakePhysicalMidiIn:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls
        self.callback = None

    def get_ports(self) -> list[str]:
        return ["Digital Piano"]

    def ignore_types(self, **options) -> None:
        self.calls.append(("ignore_types", options))

    def set_callback(self, callback) -> None:
        self.callback = callback
        self.calls.append(("set_physical_callback", None))

    def open_port(self, index: int, name: str) -> None:
        self.calls.append(("open_physical", (index, name)))

    def cancel_callback(self) -> None:
        self.calls.append(("cancel_physical", None))

    def close_port(self) -> None:
        self.calls.append(("close_physical", None))


class FakeRtMidi:
    def __init__(self, midi_in: FakePhysicalMidiIn) -> None:
        self._midi_in = midi_in

    def MidiIn(self) -> FakePhysicalMidiIn:
        return self._midi_in


def test_managed_virtual_router_forwards_before_observer_and_cleans_up() -> None:
    calls: list[tuple[str, object]] = []
    driver = FakeVirtualDriver(calls)
    router = MidiRouter(
        MidiRouterConfig(
            input_port=VIRTUAL_INPUT_PORT_NAME,
            output_port=VIRTUAL_OUTPUT_PORT_NAME,
            managed_virtual_ports=True,
        ),
        RecordingDispatcher(calls),  # type: ignore[arg-type]
        virtual_driver_factory=lambda: driver,
    )

    router.start()
    assert driver.input is not None
    driver.input.callback([0x90, 60, 100])
    assert calls[-2:] == [("send", (0x90, 60, 100)), ("publish", (0x90, 60, 100))]

    router.stop()
    assert ("close_input", None) in calls
    assert calls[-1] == ("close_output", None)
    assert calls.index(("close_input", None)) < calls.index(("close_output", None))


def test_managed_virtual_router_filters_optional_system_messages() -> None:
    calls: list[tuple[str, object]] = []
    driver = FakeVirtualDriver(calls)
    router = MidiRouter(
        MidiRouterConfig(
            input_port=VIRTUAL_INPUT_PORT_NAME,
            output_port=VIRTUAL_OUTPUT_PORT_NAME,
            managed_virtual_ports=True,
        ),
        RecordingDispatcher(calls),  # type: ignore[arg-type]
        virtual_driver_factory=lambda: driver,
    )
    router.start()
    assert driver.input is not None

    driver.input.callback([0xF0, 0x01, 0xF7])
    driver.input.callback([0xF8])
    driver.input.callback([0xFE])

    assert not any(kind in {"send", "publish"} for kind, _ in calls)
    router.stop()


def test_managed_router_can_select_one_physical_input(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    driver = FakeVirtualDriver(calls)
    physical_input = FakePhysicalMidiIn(calls)
    monkeypatch.setattr(
        router_module,
        "_load_rtmidi",
        lambda: FakeRtMidi(physical_input),
    )
    router = MidiRouter(
        MidiRouterConfig(
            input_port="Digital Piano",
            output_port=VIRTUAL_OUTPUT_PORT_NAME,
            managed_virtual_ports=True,
        ),
        RecordingDispatcher(calls),  # type: ignore[arg-type]
        virtual_driver_factory=lambda: driver,
    )

    router.start()

    assert driver.input is None
    assert router.input_name == "Digital Piano"
    assert physical_input.callback is not None
    physical_input.callback(([0x90, 60, 100], 0.0), None)
    assert calls[-2:] == [("send", (0x90, 60, 100)), ("publish", (0x90, 60, 100))]

    router.stop()
    assert ("close_physical", None) in calls
    assert calls[-1] == ("close_output", None)


def test_controller_refuses_start_when_driver_is_missing() -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher()
    controller = MidiController(
        dispatcher,
        status_provider=lambda: VirtualMidiStatus(
            available=False,
            message="请安装 teVirtualMIDI",
        ),
    )

    try:
        controller.start(AppSettings())
    except RuntimeError as exc:
        assert str(exc) == "请安装 teVirtualMIDI"
    else:
        raise AssertionError("controller unexpectedly started without the driver")
