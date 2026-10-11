from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING

from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.router import MidiRouter, MidiRouterConfig
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    virtual_midi_status,
)

from .config import AppSettings
from .dispatcher import EventDispatcher

if TYPE_CHECKING:
    from .key_mapping import KeyboardMappingService


class MidiController:
    """Own the router lifecycle for HTTP control without touching observers."""

    def __init__(
        self,
        dispatcher: EventDispatcher[MidiEvent],
        *,
        router_factory=MidiRouter,
        status_provider=virtual_midi_status,
        keyboard_mapper: KeyboardMappingService | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self._lock = RLock()
        self._router: MidiRouter | None = None
        self._last_error: str | None = None
        self._router_factory = router_factory
        self._status_provider = status_provider
        self._keyboard_mapper = keyboard_mapper

    def start(self, settings: AppSettings) -> dict[str, object]:
        with self._lock:
            if self._router is not None:
                return self.status()
            driver_status = self._status_provider()
            if not driver_status.available:
                self._last_error = driver_status.message
                raise RuntimeError(driver_status.message)
            router = self._router_factory(
                MidiRouterConfig(
                    input_port=settings.input_port,
                    output_port=VIRTUAL_OUTPUT_PORT_NAME,
                    managed_virtual_ports=True,
                    receive_sysex=settings.receive_sysex,
                    receive_clock=settings.receive_clock,
                    receive_active_sensing=settings.receive_active_sensing,
                    panic_on_stop=settings.panic_on_stop,
                    fixed_half_pedal_enabled=settings.fixed_half_pedal_enabled,
                    pedal_depth=settings.pedal_depth,
                ),
                self.dispatcher,
            )
            callback_setter = getattr(router, "set_post_forward_callback", None)
            if callback_setter is not None and self._keyboard_mapper is not None:
                callback_setter(self._keyboard_mapper.offer_midi)
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
            if self._keyboard_mapper is not None:
                self._keyboard_mapper.release_all()
            return self.status()

    def update_pedal_settings(self, settings: AppSettings) -> None:
        with self._lock:
            if self._router is not None:
                self._router.update_pedal_settings(
                    enabled=settings.fixed_half_pedal_enabled,
                    depth=settings.pedal_depth,
                )

    def status(self) -> dict[str, object]:
        with self._lock:
            router = self._router
            driver_status = self._status_provider()
            return {
                "running": router is not None,
                "input_port": (
                    router.input_name if router is not None else VIRTUAL_INPUT_PORT_NAME
                ),
                "output_port": (
                    router.output_name if router is not None else VIRTUAL_OUTPUT_PORT_NAME
                ),
                "driver": driver_status.to_dict(),
                "last_error": self._last_error,
                "router_metrics": router.metrics.snapshot() if router is not None else None,
                "dispatcher_metrics": self.dispatcher.metrics.snapshot(),
            }
