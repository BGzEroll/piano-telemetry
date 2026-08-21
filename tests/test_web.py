from pathlib import Path

from fastapi.testclient import TestClient

from piano_telemetry.core.config import AppSettings, SettingsStore
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.ports import MidiPorts
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    VirtualMidiStatus,
)
from piano_telemetry.web_server import create_web_app


class FakeMetrics:
    def snapshot(self) -> dict[str, int]:
        return {}


class TrackingRouter:
    instances = []

    def __init__(self, config, dispatcher) -> None:
        self.config = config
        self.dispatcher = dispatcher
        self.input_name = None
        self.output_name = None
        self.metrics = FakeMetrics()
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.input_name = self.config.input_port
        self.output_name = self.config.output_port

    def stop(self) -> None:
        self.stopped = True


def available_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=True, message="ready")


def missing_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=False, message="请先安装 teVirtualMIDI")


def available_ports() -> MidiPorts:
    return MidiPorts(
        inputs=("Digital Piano", "Piano Telemetry Output 0"),
        outputs=(),
    )


def test_visualization_is_home_and_redundant_labels_are_removed(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        for path in ("/", "/settings", "/visualization", "/static/app.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.content
        settings_html = client.get("/settings").text
        home_html = client.get("/").text
        visualization_html = client.get("/visualization").text
        assert "实时演奏" in home_html
        assert "LIVE PERFORMANCE" not in home_html
        assert "MIDI 路由" not in home_html
        assert 'id="route-label"' not in home_html
        assert home_html == visualization_html
        assert 'class="custom-select"' in settings_html
        assert '<select' not in settings_html
        assert "DEVICE CONFIGURATION" not in settings_html
        assert "配置实时链路" not in settings_html
        assert 'class="step-number"' not in settings_html
        assert "选择电钢输入" not in settings_html
        assert "由程序创建" not in settings_html
        assert 'class="settings-action-buttons"' in settings_html
        assert 'id="route-status"' not in settings_html


def test_settings_api_persists_input_selection_and_lists_inputs(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "input_port": "Digital Piano",
                "output_port": "Piano Telemetry Out",
                "receive_sysex": False,
                "receive_clock": True,
                "receive_active_sensing": False,
                "panic_on_stop": True,
            },
        )
        assert response.status_code == 200
        settings = client.get("/api/settings").json()
        assert settings["input_port"] == "Digital Piano"
        assert response.json()["midi_restarted"] is False
        assert settings["receive_clock"] is True
        ports = client.get("/api/midi/ports").json()
        assert ports["input_port"] == VIRTUAL_INPUT_PORT_NAME
        assert ports["output_port"] == VIRTUAL_OUTPUT_PORT_NAME
        assert ports["inputs"] == [VIRTUAL_INPUT_PORT_NAME, "Digital Piano"]
        assert ports["available"] is True
    assert store.load().receive_clock is True


def test_websocket_receives_independent_telemetry(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
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
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        ports = client.get("/api/midi/ports").json()
        assert ports["available"] is False
        assert ports["install_url"]

        response = client.post("/api/midi/start")
        assert response.status_code == 409
        assert "安装" in response.json()["detail"]


def test_startup_falls_back_to_virtual_input_starts_and_stop_closes_router(
    tmp_path: Path,
) -> None:
    TrackingRouter.instances.clear()
    store = SettingsStore(tmp_path / "config.json")
    store.save(AppSettings(input_port="Disconnected Piano", receive_clock=True))
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=TrackingRouter,
    )

    with TestClient(app) as client:
        status = client.get("/api/status").json()
        assert status["running"] is True
        assert status["input_port"] == VIRTUAL_INPUT_PORT_NAME
        assert store.load() == AppSettings(
            input_port=VIRTUAL_INPUT_PORT_NAME,
            receive_clock=True,
        )

        stopped = client.post("/api/midi/stop").json()
        assert stopped["running"] is False
        assert TrackingRouter.instances[-1].stopped is True


def test_startup_keeps_an_available_saved_physical_input(tmp_path: Path) -> None:
    TrackingRouter.instances.clear()
    store = SettingsStore(tmp_path / "config.json")
    store.save(AppSettings(input_port="Digital Piano"))
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=TrackingRouter,
    )

    with TestClient(app) as client:
        status = client.get("/api/status").json()
        assert status["running"] is True
        assert status["input_port"] == "Digital Piano"
        assert store.load().input_port == "Digital Piano"


def test_saving_settings_restarts_a_running_midi_route(tmp_path: Path) -> None:
    TrackingRouter.instances.clear()
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=TrackingRouter,
    )

    with TestClient(app) as client:
        original = TrackingRouter.instances[-1]
        response = client.put(
            "/api/settings",
            json={
                "input_port": "Digital Piano",
                "receive_sysex": True,
                "receive_clock": False,
                "receive_active_sensing": False,
                "panic_on_stop": True,
            },
        )

        assert response.status_code == 200
        assert response.json()["midi_restarted"] is True
        assert original.stopped is True
        assert len(TrackingRouter.instances) == 2
        assert TrackingRouter.instances[-1].config.input_port == "Digital Piano"
        assert TrackingRouter.instances[-1].config.receive_sysex is True
        assert client.get("/api/status").json()["running"] is True
