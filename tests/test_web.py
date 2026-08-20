from pathlib import Path

from fastapi.testclient import TestClient

from piano_telemetry.core.config import SettingsStore
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.web_server import create_web_app


def test_portal_settings_and_visualization_are_served(tmp_path: Path) -> None:
    app = create_web_app(settings_store=SettingsStore(tmp_path / "config.json"))
    with TestClient(app) as client:
        for path in ("/", "/settings", "/visualization", "/static/app.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.content


def test_settings_api_persists_port_selection(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(settings_store=store)
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
        assert client.get("/api/settings").json()["input_port"] == "Test Input"
    assert store.load().output_port == "Piano Telemetry Out"


def test_websocket_receives_independent_telemetry(tmp_path: Path) -> None:
    app = create_web_app(settings_store=SettingsStore(tmp_path / "config.json"))
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
