from __future__ import annotations

from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig


class RecordingOutput:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def send_message(self, message: list[int]) -> None:
        self.calls.append(("send", tuple(message)))


class RecordingDispatcher:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def publish_nowait(self, event) -> bool:
        self.calls.append(("publish", event.seq))
        return True


class FailingDispatcher:
    def publish_nowait(self, event) -> bool:
        raise RuntimeError("observer failed")


def test_router_sends_before_publishing() -> None:
    calls: list[tuple[str, object]] = []
    router = MidiRouter(
        MidiRouterConfig(input_port="in", output_port="out"),
        RecordingDispatcher(calls),  # type: ignore[arg-type]
    )
    router._midi_out = RecordingOutput(calls)
    router.input_name = "in"

    router._handle_message([0x90, 60, 100], captured_monotonic_ns=10)

    assert [call[0] for call in calls] == ["send", "publish"]
    assert router.metrics.events_forwarded_total == 1


def test_keyboard_mapping_callback_runs_only_after_midi_output() -> None:
    calls: list[tuple[str, object]] = []
    router = MidiRouter(
        MidiRouterConfig(input_port="in", output_port="out"),
        RecordingDispatcher(calls),  # type: ignore[arg-type]
    )
    router._midi_out = RecordingOutput(calls)
    router.set_post_forward_callback(
        lambda message: calls.append(("mapping", tuple(message)))
    )

    router._handle_message([0x90, 60, 100], captured_monotonic_ns=10)

    assert [call[0] for call in calls] == ["send", "mapping", "publish"]


def test_observer_failure_does_not_escape_after_successful_send() -> None:
    calls: list[tuple[str, object]] = []
    router = MidiRouter(
        MidiRouterConfig(input_port="in", output_port="out"),
        FailingDispatcher(),  # type: ignore[arg-type]
    )
    router._midi_out = RecordingOutput(calls)

    router._handle_message([0x80, 60, 0], captured_monotonic_ns=10)

    assert calls == [("send", (0x80, 60, 0))]
    assert router.metrics.events_forwarded_total == 1
    assert router.metrics.observer_publish_errors_total == 1
