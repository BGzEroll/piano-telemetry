from __future__ import annotations

from queue import Empty
from time import monotonic, sleep

import pytest

from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.core.subscriber import OverflowPolicy, Subscription
from piano_telemetry.midi.event import MidiEvent


def make_event(seq: int) -> MidiEvent:
    return MidiEvent.from_raw(
        seq=seq,
        captured_monotonic_ns=seq,
        source_port="test",
        raw=[0x90, 60, 80],
    )


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_dispatcher_broadcasts_without_splitting_events() -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=16)
    first = dispatcher.subscribe("first", capacity=8)
    second = dispatcher.subscribe("second", capacity=8)
    dispatcher.start()
    try:
        for seq in range(1, 4):
            assert dispatcher.publish_nowait(make_event(seq))
        wait_until(lambda: first.stats().queued == 3 and second.stats().queued == 3)

        assert [first.get_nowait().seq for _ in range(3)] == [1, 2, 3]
        assert [second.get_nowait().seq for _ in range(3)] == [1, 2, 3]
    finally:
        dispatcher.stop()


def test_slow_subscription_does_not_affect_fast_subscription() -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=16)
    slow = dispatcher.subscribe("slow", capacity=1)
    fast = dispatcher.subscribe("fast", capacity=8)
    dispatcher.start()
    try:
        for seq in range(1, 5):
            assert dispatcher.publish_nowait(make_event(seq))
        wait_until(lambda: dispatcher.metrics.dispatched_total == 4)

        assert slow.stats().dropped_total == 3
        assert slow.get_nowait().seq == 1
        assert [fast.get_nowait().seq for _ in range(4)] == [1, 2, 3, 4]
    finally:
        dispatcher.stop()


def test_ingress_full_drops_without_requiring_a_consumer() -> None:
    dispatcher: EventDispatcher[MidiEvent] = EventDispatcher(ingress_capacity=1)
    assert dispatcher.publish_nowait(make_event(1))
    assert not dispatcher.publish_nowait(make_event(2))
    assert dispatcher.metrics.ingress_drop_total == 1


def test_latest_subscription_overwrites_and_peeks() -> None:
    latest: Subscription[MidiEvent] = Subscription(
        "latest", capacity=1, overflow=OverflowPolicy.LATEST
    )
    latest.offer(make_event(1))
    latest.offer(make_event(2))

    assert latest.peek_nowait().seq == 2
    assert latest.peek_nowait().seq == 2
    assert latest.get_nowait().seq == 2
    assert latest.stats().dropped_total == 1
    with pytest.raises(Empty):
        latest.get_nowait()

