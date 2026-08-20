from __future__ import annotations

from threading import RLock

from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig

from .config import AppSettings
from .dispatcher import EventDispatcher


class MidiController:
    """Own the router lifecycle for HTTP control without touching observers."""

    def __init__(self, dispatcher: EventDispatcher[MidiEvent]) -> None:
        self.dispatcher = dispatcher
        self._lock = RLock()
        self._router: MidiRouter | None = None
        self._last_error: str | None = None

    def start(self, settings: AppSettings) -> dict[str, object]:
        if not settings.input_port or not settings.output_port:
            raise RuntimeError("请先在设置中选择 MIDI 输入和输出端口")
        with self._lock:
            if self._router is not None:
                return self.status()
            router = MidiRouter(
                MidiRouterConfig(
                    input_port=settings.input_port,
                    output_port=settings.output_port,
                    receive_sysex=settings.receive_sysex,
                    receive_clock=settings.receive_clock,
                    receive_active_sensing=settings.receive_active_sensing,
                    panic_on_stop=settings.panic_on_stop,
                ),
                self.dispatcher,
            )
            try:
                router.start()
            except Exception as exc:
                self._last_error = str(exc)
                raise
            self._router = router
            self._last_error = None
            return self.status()

    def stop(self) -> dict[str, object]:
        with self._lock:
            router = self._router
            self._router = None
            if router is not None:
                router.stop()
            return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            router = self._router
            return {
                "running": router is not None,
                "input_port": router.input_name if router is not None else None,
                "output_port": router.output_name if router is not None else None,
                "last_error": self._last_error,
                "router_metrics": router.metrics.snapshot() if router is not None else None,
                "dispatcher_metrics": self.dispatcher.metrics.snapshot(),
            }

