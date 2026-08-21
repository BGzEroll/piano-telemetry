from __future__ import annotations

import asyncio
from queue import Empty
from threading import Event, RLock, Thread

from piano_telemetry.analyzer import NoteStateTracker
from piano_telemetry.analyzer.tonality import DEFAULT_TONALITY, normalize_tonality
from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.core.subscriber import OverflowPolicy, Subscription
from piano_telemetry.midi.event import MidiEvent


class WebEventHub:
    """Bridge the synchronous dispatcher to independent asyncio client queues."""

    def __init__(
        self,
        dispatcher: EventDispatcher[MidiEvent],
        *,
        subscriber_capacity: int = 4096,
        client_capacity: int = 256,
        tonality: str = DEFAULT_TONALITY,
    ) -> None:
        self.dispatcher = dispatcher
        self.client_capacity = client_capacity
        self.subscription: Subscription[MidiEvent] = dispatcher.subscribe(
            "websocket",
            capacity=subscriber_capacity,
            overflow=OverflowPolicy.DROP_OLDEST,
        )
        self._tracker = NoteStateTracker(tonality=tonality)
        self._latest_state = self._tracker.snapshot()
        self._state_lock = RLock()
        self._clients: set[asyncio.Queue[dict[str, object]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = Event()
        self._thread: Thread | None = None
        self.client_drop_total = 0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._loop = loop
        self._stop.clear()
        self._thread = Thread(target=self._run, name="web-event-hub", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        self.dispatcher.unsubscribe("websocket")

    def register(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(
            maxsize=self.client_capacity
        )
        self._clients.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._clients.discard(queue)

    def latest_state(self) -> dict[str, object]:
        with self._state_lock:
            return dict(self._latest_state)

    def set_tonality(self, tonality: str) -> dict[str, object]:
        selected = normalize_tonality(tonality)
        with self._state_lock:
            self._tracker.set_tonality(selected)
            state = self._tracker.snapshot()
            self._latest_state = state
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._fan_out, state)
        return dict(state)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.subscription.get(timeout=0.05)
            except Empty:
                continue
            try:
                with self._state_lock:
                    state, gap = self._tracker.apply(event)
                    self._latest_state = state
                payload: dict[str, object] = {
                    "kind": "telemetry",
                    "event": event.to_dict(),
                    "state": state,
                }
                if gap is not None:
                    payload["gap"] = {"from_seq": gap[0], "to_seq": gap[1]}
                loop = self._loop
                if loop is not None and not loop.is_closed():
                    loop.call_soon_threadsafe(self._fan_out, payload)
            finally:
                self.subscription.task_done()

    def _fan_out(self, payload: dict[str, object]) -> None:
        for queue in tuple(self._clients):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                else:
                    self.client_drop_total += 1
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self.client_drop_total += 1
