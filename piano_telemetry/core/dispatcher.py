from __future__ import annotations

from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Generic, TypeVar

from .metrics import DispatcherMetrics
from .subscriber import OverflowPolicy, Subscription


T = TypeVar("T")


class EventDispatcher(Generic[T]):
    """Best-effort broadcast fan-out behind one bounded ingress queue."""

    def __init__(self, *, ingress_capacity: int = 4096) -> None:
        if ingress_capacity < 1:
            raise ValueError("ingress_capacity must be at least 1")
        self._ingress: Queue[T] = Queue(maxsize=ingress_capacity)
        self._subscriptions: dict[str, Subscription[T]] = {}
        self._subscriptions_lock = Lock()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self.metrics = DispatcherMetrics()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = Thread(target=self._run, name="midi-event-dispatcher", daemon=True)
        self._thread.start()

    def stop(self, *, drain: bool = True, timeout: float = 2.0) -> None:
        self._stop_requested.set()
        thread = self._thread
        if thread is None:
            return
        if not drain:
            self._discard_ingress()
        thread.join(timeout=timeout)
        self._thread = None

    def publish_nowait(self, item: T) -> bool:
        """Try to publish without waiting for queue capacity."""
        self.metrics.publish_attempted_total += 1
        try:
            self._ingress.put_nowait(item)
        except Full:
            self.metrics.ingress_drop_total += 1
            return False
        self.metrics.ingress_accepted_total += 1
        return True

    def subscribe(
        self,
        name: str,
        *,
        capacity: int = 1024,
        overflow: OverflowPolicy = OverflowPolicy.DROP_NEWEST,
    ) -> Subscription[T]:
        subscription = Subscription[T](name, capacity=capacity, overflow=overflow)
        with self._subscriptions_lock:
            if name in self._subscriptions:
                raise ValueError(f"subscription already exists: {name}")
            self._subscriptions[name] = subscription
        return subscription

    def unsubscribe(self, name: str) -> None:
        with self._subscriptions_lock:
            self._subscriptions.pop(name, None)

    def subscription_stats(self) -> list[dict[str, object]]:
        with self._subscriptions_lock:
            subscriptions = tuple(self._subscriptions.values())
        return [vars_as_dict(subscription.stats()) for subscription in subscriptions]

    def unfinished_tasks(self) -> int:
        with self._ingress.mutex:
            return self._ingress.unfinished_tasks

    def wait_until_idle(self, *, timeout: float) -> bool:
        """Wait outside the realtime path until accepted ingress work is dispatched."""
        deadline = monotonic() + max(0.0, timeout)
        while self.unfinished_tasks() > 0:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            self._stop_requested.wait(min(0.005, remaining))
        return True

    def _run(self) -> None:
        while not self._stop_requested.is_set() or not self._ingress.empty():
            try:
                item = self._ingress.get(timeout=0.05)
            except Empty:
                continue

            with self._subscriptions_lock:
                subscriptions = tuple(self._subscriptions.values())
            for subscription in subscriptions:
                try:
                    subscription.offer(item)
                except Exception:
                    self.metrics.dispatch_errors_total += 1
            self.metrics.dispatched_total += 1
            self._ingress.task_done()

    def _discard_ingress(self) -> None:
        while True:
            try:
                self._ingress.get_nowait()
            except Empty:
                return
            else:
                self._ingress.task_done()


def vars_as_dict(value: object) -> dict[str, object]:
    return {
        field: getattr(value, field)
        for field in getattr(value, "__dataclass_fields__", {})
    }
