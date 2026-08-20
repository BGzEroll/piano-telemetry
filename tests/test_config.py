from pathlib import Path

import piano_telemetry.core.config as config_module
from piano_telemetry.core.config import AppSettings, SettingsStore


def test_settings_round_trip_uses_explicit_path(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    settings = AppSettings(
        input_port="Digital Piano",
        output_port="Piano Telemetry Out",
        receive_clock=True,
    )

    store.save(settings)

    assert store.load() == settings
    assert store.path.parent == tmp_path


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
