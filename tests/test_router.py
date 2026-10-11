from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

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


def pedal_router(*, enabled=False, depth=80):
    calls = []
    router = MidiRouter(
        MidiRouterConfig(
            input_port="in", output_port="out", panic_on_stop=False,
            fixed_half_pedal_enabled=enabled, pedal_depth=depth,
        ),
        RecordingDispatcher(calls),
    )
    router._midi_out = RecordingOutput(calls)
    return router, calls


def send(router, message):
    router._handle_message(message, captured_monotonic_ns=10)


def sent(calls):
    return [message for kind, message in calls if kind == "send"]


def test_held_pedals_synchronize_depth_and_restore_original_per_channel() -> None:
    router, calls = pedal_router()
    send(router, [0xB0, 64, 127])
    send(router, [0xBF, 64, 100])
    send(router, [0xB2, 64, 0])
    router.update_pedal_settings(enabled=True, depth=80)
    assert sent(calls)[-2:] == [(0xB0, 64, 80), (0xBF, 64, 80)]
    router.update_pedal_settings(enabled=True, depth=64)
    assert sent(calls)[-2:] == [(0xB0, 64, 64), (0xBF, 64, 64)]
    router.update_pedal_settings(enabled=False, depth=90)
    assert sent(calls)[-2:] == [(0xB0, 64, 127), (0xBF, 64, 100)]
    before = list(calls)
    router.update_pedal_settings(enabled=False, depth=127)
    assert calls == before
    assert router.metrics.events_received_total == router.metrics.events_forwarded_total == 3
    assert router.metrics.pedal_updates_total == 6


def test_unknown_and_released_channels_do_not_acquire_sustain() -> None:
    router, calls = pedal_router()
    router.update_pedal_settings(enabled=True, depth=90)
    assert calls == []
    send(router, [0xB0, 64, 127])
    assert sent(calls) == [(0xB0, 64, 90)]
    send(router, [0xB0, 64, 63])
    assert sent(calls)[-1] == (0xB0, 64, 0)
    before = list(calls)
    router.update_pedal_settings(enabled=False, depth=100)
    router.update_pedal_settings(enabled=True, depth=127)
    assert calls == before


def test_output_values_reach_mapping_and_telemetry_after_sending() -> None:
    router, calls = pedal_router(enabled=True)
    observed = []

    class Dispatcher:
        def publish_nowait(self, event):
            calls.append(("publish", event.raw))
            observed.append(event)

    router.dispatcher = Dispatcher()
    router.set_post_forward_callback(lambda message: calls.append(("mapping", tuple(message))))
    send(router, [0xBA, 64, 127])
    router.update_pedal_settings(enabled=True, depth=95)
    send(router, [0xBA, 64, 0])
    assert [event.raw for event in observed] == [(0xBA, 64, 80), (0xBA, 64, 95), (0xBA, 64, 0)]
    assert [event.seq for event in observed] == [1, 2, 3]
    assert [kind for kind, _ in calls] == ["send", "mapping", "publish"] * 3


@pytest.mark.parametrize("reset", [[0xB3, 121, 0], [0xFF]])
def test_controller_reset_does_not_resurrect_old_pedal(reset) -> None:
    router, calls = pedal_router(enabled=True)
    send(router, [0xB3, 64, 127])
    send(router, reset)
    before = list(calls)
    router.update_pedal_settings(enabled=True, depth=90)
    assert calls == before


def test_stop_discards_pedal_state() -> None:
    router, calls = pedal_router()
    send(router, [0xB0, 64, 127])
    router.stop()
    # An input callback already in flight may arrive after stop detached the output.
    send(router, [0xB0, 64, 127])
    router._midi_out = RecordingOutput(calls)
    before = list(calls)
    router.update_pedal_settings(enabled=True, depth=90)
    assert calls == before


def test_failed_setting_send_is_reported_and_can_be_retried() -> None:
    router, calls = pedal_router()
    send(router, [0xB0, 64, 127])
    send(router, [0xB1, 64, 100])

    class FailingOutput(RecordingOutput):
        def send_message(self, message):
            if message[0] == 0xB0:
                raise RuntimeError("output failed")
            super().send_message(message)

    router._midi_out = FailingOutput(calls)
    with pytest.raises(RuntimeError, match="synchronize"):
        router.update_pedal_settings(enabled=True, depth=80)
    assert router.metrics.pedal_update_errors_total == 1
    assert sent(calls)[-1] == (0xB1, 64, 80)
    router._midi_out = RecordingOutput(calls)
    router.update_pedal_settings(enabled=True, depth=80)
    assert sent(calls)[-1] == (0xB0, 64, 80)


def test_release_cannot_be_overtaken_by_stale_setting_output_and_notes_do_not_wait() -> None:
    router, calls = pedal_router()
    send(router, [0xB0, 64, 127])
    updating = Event()
    continue_send = Event()
    releasing = Event()

    class BlockingOutput(RecordingOutput):
        def send_message(self, message):
            if message == [0xB0, 64, 80]:
                updating.set()
                assert continue_send.wait(2)
            super().send_message(message)

    router._midi_out = BlockingOutput(calls)

    def release():
        releasing.set()
        send(router, [0xB0, 64, 0])

    with ThreadPoolExecutor(max_workers=3) as executor:
        update = executor.submit(router.update_pedal_settings, enabled=True, depth=80)
        try:
            assert updating.wait(2)
            release_task = executor.submit(release)
            assert releasing.wait(2)
            note = executor.submit(send, router, [0x90, 60, 100])
            note.result(timeout=1)
        finally:
            continue_send.set()
        update.result(timeout=2)
        release_task.result(timeout=2)
    assert sent(calls) == [(0xB0, 64, 127), (0x90, 60, 100), (0xB0, 64, 80), (0xB0, 64, 0)]
