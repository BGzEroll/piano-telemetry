from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class RouterMetrics:
    """MIDI input counters and separate runtime pedal synchronization counters."""

    events_received_total: int = 0
    events_forwarded_total: int = 0
    forward_errors_total: int = 0
    observer_publish_errors_total: int = 0
    shutdown_errors_total: int = 0
    pedal_updates_total: int = 0
    pedal_update_errors_total: int = 0

    def snapshot(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class DispatcherMetrics:
    """Counters for the ingress queue and dispatcher worker."""

    publish_attempted_total: int = 0
    ingress_accepted_total: int = 0
    ingress_drop_total: int = 0
    dispatched_total: int = 0
    dispatch_errors_total: int = 0

    def snapshot(self) -> dict[str, int]:
        return asdict(self)
