from pathlib import Path

import pytest

import piano_telemetry.core.config as config_module
from piano_telemetry.core.config import AppSettings, SettingsStore


def test_settings_round_trip_uses_explicit_path(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    settings = AppSettings(
        input_port="Digital Piano",
        receive_clock=True,
    )

    store.save(settings)

    assert store.load() == settings
    assert store.path.parent == tmp_path


def test_input_port_selection_is_preserved_but_output_port_is_ignored() -> None:
    settings = AppSettings.from_dict(
        {
            "input_port": "Old Input",
            "output_port": "Old Output",
            "receive_clock": True,
        }
    )

    assert settings == AppSettings(input_port="Old Input", receive_clock=True)
    assert settings.to_dict()["input_port"] == "Old Input"
    assert "output_port" not in settings.to_dict()


def test_blank_input_port_falls_back_to_managed_virtual_input() -> None:
    assert AppSettings.from_dict({"input_port": "  "}) == AppSettings()


def test_invalid_settings_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")
    assert SettingsStore(path).load() == AppSettings()


def test_frozen_app_stores_generated_data_beside_exe(
    tmp_path: Path, monkeypatch
) -> None:
    exe_path = tmp_path / "PianoTelemetry.exe"
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", str(exe_path))

    assert config_module.default_data_dir() == tmp_path / "data"
    assert config_module.default_sessions_dir() == tmp_path / "data" / "sessions"
    assert SettingsStore().path == tmp_path / "data" / "config.json"


def test_tonality_is_validated_and_persisted(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    store.save(AppSettings(tonality="Eb_minor"))
    assert store.load().tonality == "Eb_minor"

    assert AppSettings.from_dict({"tonality": "not-a-key"}).tonality == "C_major"


def test_pedal_settings_defaults_and_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "data" / "config.json")
    assert store.load().fixed_half_pedal_enabled is False
    assert store.load().pedal_depth == 80
    settings = AppSettings(fixed_half_pedal_enabled=True, pedal_depth=95)
    store.save(settings)
    assert SettingsStore(store.path).load() == settings
    assert AppSettings.from_dict({"receive_sysex": True}).pedal_depth == 80


@pytest.mark.parametrize("value,expected", [
    (0, 64), (200, 127), (64, 64), (127, 127),
    ("90", 80), (None, 80), (True, 80), (80.5, 80),
])
def test_saved_pedal_depth_is_normalized(value, expected) -> None:
    assert AppSettings.from_dict({"pedal_depth": value}).pedal_depth == expected
