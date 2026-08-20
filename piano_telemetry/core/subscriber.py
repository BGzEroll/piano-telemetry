from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from queue import Empty, Full, Queue
from typing import Generic, TypeVar


T = TypeVar("T")


class OverflowPolicy(str, Enum):
    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"
    LATEST = "latest"


@dataclass(frozen=True, slots=True)
class SubscriptionStats:
    name: str
    capacity: int
    queued: int
    accepted_total: int
    dropped_total: int
    first_dropped_seq: int | None
    last_dropped_seq: int | None


class Subscription(Generic[T]):
    """An independent bounded queue owned by exactly one subscriber."""

    def __init__(
        self,
        name: str,
        *,
        capacity: int,
        overflow: OverflowPolicy = OverflowPolicy.DROP_NEWEST,
    ) -> None:
        if capacity < 1:
            raise ValueError("subscription capacity must be at least 1")
        if overflow is OverflowPolicy.LATEST and capacity != 1:
            raise ValueError("LATEST subscriptions must have capacity=1")

        self.name = name
        self.capacity = capacity
        self.overflow = overflow
        self._queue: Queue[T] = Queue(maxsize=capacity)
        self._accepted_total = 0
        self._dropped_total = 0
        self._first_dropped_seq: int | None = None
        self._last_dropped_seq: int | None = None

    def offer(self, item: T) -> bool:
        try:
            self._queue.put_nowait(item)
            self._accepted_total += 1
            return True
        except Full:
            if self.overflow is OverflowPolicy.DROP_NEWEST:
                self._mark_dropped(item)
                return False

        # DROP_OLDEST and LATEST use RTOS-style overwrite semantics.
        try:
            dropped = self._queue.get_nowait()
        except Empty:
            dropped = None
        if dropped is not None:
            self._mark_dropped(dropped)

        try:
            self._queue.put_nowait(item)
            self._accepted_total += 1
            return True
        except Full:
            # A concurrent consumer/producer race must still never block.
            self._mark_dropped(item)
            return False

    def get(self, *, timeout: float | None = None) -> T:
        if timeout is None:
            return self._queue.get()
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> T:
        return self._queue.get_nowait()

    def task_done(self) -> None:
        self._queue.task_done()

    def unfinished_tasks(self) -> int:
        with self._queue.mutex:
            return self._queue.unfinished_tasks

    def peek_nowait(self) -> T:
        """Return the current head without consuming it.

        Queue does not expose peek publicly. Access is protected by the same
        mutex used by Queue's own operations, matching mailbox peek semantics.
        """
        with self._queue.mutex:
            if not self._queue.queue:
                raise Empty
            return self._queue.queue[0]

    def stats(self) -> SubscriptionStats:
        return SubscriptionStats(
            name=self.name,
            capacity=self.capacity,
            queued=self._queue.qsize(),
            accepted_total=self._accepted_total,
            dropped_total=self._dropped_total,
            first_dropped_seq=self._first_dropped_seq,
            last_dropped_seq=self._last_dropped_seq,
        )

    def _mark_dropped(self, item: T) -> None:
        self._dropped_total += 1
        seq = getattr(item, "seq", None)
        if not isinstance(seq, int):
            return
        if self._first_dropped_seq is None:
            self._first_dropped_seq = seq
        self._last_dropped_seq = seq
