from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep

from piano_telemetry.core.key_mapping import (
    KeyboardMappingService,
    KeyboardMappingSettings,
    KeyboardMappingStore,
)


class FakeKeySender:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    def send(self, key_code: str, *, pressed: bool) -> None:
        self.events.append((key_code, pressed))


def wait_for_events(sender: FakeKeySender, count: int) -> None:
    deadline = monotonic() + 0.5
    while len(sender.events) < count and monotonic() < deadline:
        sleep(0.005)
    assert len(sender.events) >= count


def test_mapping_service_emits_key_down_and_up_without_midi_thread_waiting(
    tmp_path: Path,
) -> None:
    sender = FakeKeySender()
    store = KeyboardMappingStore(tmp_path / "key_mapping.json")
    service = KeyboardMappingService(store, sender=sender)
    service.apply(
        KeyboardMappingSettings(enabled=True, bindings=((60, "KeyA"),))
    )
    service.start()
    try:
        assert service.offer_midi([0x90, 60, 100]) is True
        assert service.offer_midi([0x90, 60, 0]) is True
        wait_for_events(sender, 2)
        assert sender.events == [("KeyA", True), ("KeyA", False)]
    finally:
        service.stop()


def test_shared_keyboard_target_uses_reference_count_and_disable_releases(
    tmp_path: Path,
) -> None:
    sender = FakeKeySender()
    service = KeyboardMappingService(
        KeyboardMappingStore(tmp_path / "key_mapping.json"),
        sender=sender,
    )
    service.apply(
        KeyboardMappingSettings(
            enabled=True,
            bindings=((60, "Digit1"), (64, "Digit1")),
        )
    )
    service.start()
    try:
        service.offer_midi([0x90, 60, 90])
        service.offer_midi([0x90, 64, 90])
        service.offer_midi([0x80, 60, 0])
        wait_for_events(sender, 1)
        assert sender.events == [("Digit1", True)]

        service.apply(KeyboardMappingSettings())
        wait_for_events(sender, 2)
        assert sender.events[-1] == ("Digit1", False)
        assert service.status()["active_notes"] == []
    finally:
        service.stop()


def test_mapping_store_round_trip_and_strict_validation(tmp_path: Path) -> None:
    store = KeyboardMappingStore(tmp_path / "key_mapping.json")
    settings = KeyboardMappingSettings(
        enabled=True,
        bindings=((21, "KeyZ"), (108, "Digit0")),
    )
    store.save(settings)
    assert store.load() == settings

    try:
        KeyboardMappingSettings.from_dict(
            {"enabled": True, "bindings": {"60": "Numpad1"}},
            strict=True,
        )
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:
        raise AssertionError("Numpad binding should be rejected")
