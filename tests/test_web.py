from pathlib import Path

from fastapi.testclient import TestClient

from piano_telemetry.core.config import SettingsStore
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    VirtualMidiStatus,
)
from piano_telemetry.web_server import create_web_app


def available_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=True, message="ready")


def missing_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=False, message="请先安装 teVirtualMIDI")


def test_portal_settings_and_visualization_are_served(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
    )
    with TestClient(app) as client:
        for path in ("/", "/settings", "/visualization", "/static/app.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.content


def test_settings_api_persists_options_but_not_port_selection(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
    )
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "input_port": "Test Input",
                "output_port": "Piano Telemetry Out",
                "receive_sysex": False,
                "receive_clock": True,
                "receive_active_sensing": False,
                "panic_on_stop": True,
            },
        )
        assert response.status_code == 200
        settings = client.get("/api/settings").json()
        assert "input_port" not in settings
        assert settings["receive_clock"] is True
        ports = client.get("/api/midi/ports").json()
        assert ports["input_port"] == VIRTUAL_INPUT_PORT_NAME
        assert ports["output_port"] == VIRTUAL_OUTPUT_PORT_NAME
        assert ports["available"] is True
    assert store.load().receive_clock is True


def test_websocket_receives_independent_telemetry(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            assert websocket.receive_json()["kind"] == "state"
            event = MidiEvent.from_raw(
                seq=1,
                captured_monotonic_ns=1,
                source_port="test",
                raw=[0x90, 60, 100],
            )
            assert app.state.dispatcher.publish_nowait(event)
            payload = websocket.receive_json()
            assert payload["kind"] == "telemetry"
            assert payload["state"]["physical_notes"] == [60]


def test_missing_virtual_midi_driver_prevents_start(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=missing_driver,
    )
    with TestClient(app) as client:
        ports = client.get("/api/midi/ports").json()
        assert ports["available"] is False
        assert ports["install_url"]

        response = client.post("/api/midi/start")
        assert response.status_code == 409
        assert "安装" in response.json()["detail"]
