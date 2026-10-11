from pathlib import Path
from time import perf_counter_ns

import pytest

from fastapi.testclient import TestClient

from piano_telemetry.core.config import AppSettings, SettingsStore
from piano_telemetry.core.key_mapping import KeyboardMappingStore
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.ports import MidiPorts
from piano_telemetry.midi.router import MidiRouter
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

    def update_pedal_settings(self, *, enabled: bool, depth: int) -> None:
        from dataclasses import replace

        self.config = replace(
            self.config, fixed_half_pedal_enabled=enabled, pedal_depth=depth
        )


def available_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=True, message="ready")


def missing_driver() -> VirtualMidiStatus:
    return VirtualMidiStatus(available=False, message="请先安装 teVirtualMIDI")


def available_ports() -> MidiPorts:
    return MidiPorts(
        inputs=("Digital Piano", "Piano Telemetry Output 0"),
        outputs=(),
    )


class MemoryOutput:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(tuple(message))

    def close_port(self):
        pass


class MemoryRouter(MidiRouter):
    """Exercise real routing and live updates without requiring a MIDI device."""

    def start(self):
        self._midi_out = MemoryOutput()
        self.input_name = self.config.input_port
        self.output_name = self.config.output_port


def test_live_pedal_api_keeps_router_and_updates_recording_and_state(tmp_path: Path) -> None:
    import json
    import mido

    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=MemoryRouter,
    )

    def receive_midi_state(websocket):
        while True:
            payload = websocket.receive_json()
            if payload["kind"] == "telemetry":
                return payload["state"]

    with TestClient(app) as client:
        defaults = client.get("/api/settings").json()
        assert defaults["fixed_half_pedal_enabled"] is False
        assert defaults["pedal_depth"] == 80
        page = client.get("/settings").text
        assert 'id="fixed-half-pedal-enabled"' in page
        assert 'type="range" min="64" max="127" step="1" value="80"' in page
        router = app.state.midi_controller._router
        output = router._midi_out
        assert client.post("/api/recording/start", json={}).status_code == 200

        with client.websocket_connect("/ws") as websocket:
            websocket.receive_json()
            router._handle_message([0xB5, 64, 100], captured_monotonic_ns=perf_counter_ns())
            assert receive_midi_state(websocket)["sustain"] == 100
            for enabled, depth, expected in [(True, 80, 80), (True, 95, 95), (False, 95, 100)]:
                response = client.put("/api/settings", json={
                    "fixed_half_pedal_enabled": enabled, "pedal_depth": depth,
                })
                assert response.status_code == 200
                assert response.json()["midi_restarted"] is False
                assert app.state.midi_controller._router is router
                assert router._midi_out is output
                assert output.messages[-1] == (0xB5, 64, expected)
                assert receive_midi_state(websocket)["sustain"] == expected

            router._handle_message([0xB5, 64, 0], captured_monotonic_ns=perf_counter_ns())
            assert receive_midi_state(websocket)["sustain"] == 0
            before = list(output.messages)
            response = client.put("/api/settings", json={
                "fixed_half_pedal_enabled": True, "pedal_depth": 90,
            })
            assert response.status_code == 200
            assert output.messages == before
        stopped = client.post("/api/recording/stop").json()
        session_dir = Path(stopped["result"]["directory"])
        payloads = [json.loads(line) for line in (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        expected = [(0xB5, 64, value) for value in [100, 80, 95, 100, 0]]
        assert [tuple(payload["raw"]) for payload in payloads] == expected
        midi = mido.MidiFile(session_dir / "session.mid")
        assert [tuple(message.bytes()) for message in midi.tracks[0] if not message.is_meta] == expected
        assert stopped["result"]["complete"] is True

    # A new application loads saved settings; no held-pedal state survives restart.
    restarted_app = create_web_app(
        settings_store=SettingsStore(store.path),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=MemoryRouter,
    )
    with TestClient(restarted_app) as client:
        router = restarted_app.state.midi_controller._router
        assert router.config.fixed_half_pedal_enabled is True
        assert router.config.pedal_depth == 90
        assert router._midi_out.messages == []
        router._handle_message([0xBF, 64, 127], captured_monotonic_ns=perf_counter_ns())
        assert router._midi_out.messages == [(0xBF, 64, 90)]


@pytest.mark.parametrize("depth", [63, 128, 80.5, "80", True, None])
def test_pedal_api_rejects_invalid_depth_without_saving(tmp_path: Path, depth) -> None:
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store, virtual_status_provider=available_driver,
        midi_ports_provider=available_ports, auto_start_midi=False,
    )
    with TestClient(app) as client:
        response = client.put("/api/settings", json={"pedal_depth": depth})
        assert response.status_code == 422
        assert store.load() == AppSettings()


def test_visualization_is_home_and_redundant_labels_are_removed(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        for path in (
            "/",
            "/settings",
            "/mapping",
            "/sessions",
            "/visualization",
            "/static/app.css",
            "/static/visualization.js",
            "/static/mapping.js",
            "/static/sessions.js",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert response.content
        settings_html = client.get("/settings").text
        home_html = client.get("/").text
        visualization_html = client.get("/visualization").text
        visualization_js = client.get("/static/visualization.js").text
        assert "实时演奏" in home_html
        assert "LIVE PERFORMANCE" not in home_html
        assert "MIDI 路由" not in home_html
        assert 'id="route-label"' not in home_html
        assert "MIDI WATERFALL" not in home_html
        assert "C1 — C8" not in home_html
        assert 'id="record-toggle"' in home_html
        assert 'id="record-save-name"' in home_html
        assert 'id="push-dialog-backdrop"' in home_html
        assert 'id="tonality-select"' in home_html
        assert '>当前调式<' in home_html
        assert '>当前和弦<' in home_html
        assert home_html.index('>当前调式<') < home_html.index('>当前和弦<')
        assert home_html.index('>当前和弦<') < home_html.index('>力度<')
        assert '>保存</button>' in home_html
        assert '>不保存</button>' in home_html
        assert home_html == visualization_html
        assert "drawCurrentStaff(width, height)" in visualization_js
        assert "drawKeySignature" in visualization_js
        assert "Math.max(0, Math.min(yTop, yBottom))" not in visualization_js
        assert 'class="custom-select"' in settings_html
        assert '<select' not in settings_html
        assert "DEVICE CONFIGURATION" not in settings_html
        assert "配置实时链路" not in settings_html
        assert 'class="step-number"' not in settings_html
        assert "选择电钢输入" not in settings_html
        assert "由程序创建" not in settings_html
        assert 'class="settings-action-buttons"' in settings_html
        assert 'id="route-status"' not in settings_html
        assert 'id="push-server-url"' in settings_html
        assert 'id="push-token"' in settings_html


def test_key_mapping_page_and_api_persist_bindings(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    mapping_store = KeyboardMappingStore(tmp_path / "key_mapping.json")
    app = create_web_app(
        settings_store=store,
        keyboard_mapping_store=mapping_store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        page = client.get("/mapping")
        assert page.status_code == 200
        assert "按键映射" in page.text
        assert 'id="mapping-enabled"' in page.text
        assert 'id="preset-select"' in page.text
        assert 'id="preset-dialog"' in page.text
        assert 'id="clear-all-bindings"' in page.text

        response = client.put(
            "/api/key-mapping",
            json={"enabled": True, "bindings": {"60": "KeyA", "64": "Digit1"}},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        assert response.json()["bindings"] == {"60": "KeyA", "64": "Digit1"}
        assert client.get("/api/key-mapping").json()["bindings"]["60"] == "KeyA"

        invalid = client.put(
            "/api/key-mapping",
            json={"enabled": True, "bindings": {"60": "Numpad1"}},
        )
        assert invalid.status_code == 422

    assert mapping_store.load().bindings == ((60, "KeyA"), (64, "Digit1"))


def test_key_mapping_presets_support_chinese_and_preserve_enabled_state(
    tmp_path: Path,
) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        client.put(
            "/api/key-mapping",
            json={"enabled": True, "bindings": {"60": "KeyA"}},
        )
        created = client.post(
            "/api/key-mapping/presets",
            json={"name": "鸣潮 战斗映射"},
        )
        assert created.status_code == 200
        preset = created.json()["preset"]
        assert preset["name"] == "鸣潮 战斗映射"
        assert preset["bindings"] == {"60": "KeyA"}

        client.put(
            "/api/key-mapping",
            json={"enabled": True, "bindings": {"64": "KeyD"}},
        )
        applied = client.post(
            f"/api/key-mapping/presets/{preset['id']}/apply"
        )
        assert applied.status_code == 200
        assert applied.json()["mapping"]["enabled"] is True
        assert applied.json()["mapping"]["bindings"] == {"60": "KeyA"}

        duplicate = client.post(
            "/api/key-mapping/presets",
            json={"name": "鸣潮 战斗映射"},
        )
        assert duplicate.status_code == 409
        assert len(client.get("/api/key-mapping/presets").json()["presets"]) == 1

        deleted = client.delete(f"/api/key-mapping/presets/{preset['id']}")
        assert deleted.status_code == 200
        assert client.get("/api/key-mapping/presets").json()["presets"] == []


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


def test_tonality_api_persists_and_updates_chord_spelling(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        options = client.get("/api/tonality").json()
        assert len(options["options"]) == 24
        assert options["tonality"] == "C_major"

        with client.websocket_connect("/ws") as websocket:
            assert websocket.receive_json()["tonality"] == "C_major"
            response = client.put("/api/tonality", json={"tonality": "Db_major"})
            assert response.status_code == 200
            assert response.json()["state"]["tonality"] == "Db_major"
            assert websocket.receive_json()["tonality"] == "Db_major"
            assert store.load().tonality == "Db_major"

            latest = None
            for seq, note in enumerate((61, 65, 68), start=1):
                assert app.state.dispatcher.publish_nowait(
                    MidiEvent.from_raw(
                        seq=seq,
                        captured_monotonic_ns=seq,
                        source_port="test",
                        raw=[0x90, note, 90],
                    )
                )
                latest = websocket.receive_json()["state"]
            assert latest["chord"] == "Db"


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


def test_push_only_settings_are_masked_and_do_not_restart_midi(tmp_path: Path) -> None:
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
                "input_port": VIRTUAL_INPUT_PORT_NAME,
                "push_enabled": True,
                "push_server_url": "http://192.168.1.20:8767/",
                "push_token": "local-secret",
            },
        )

        assert response.status_code == 200
        assert response.json()["midi_restarted"] is False
        assert response.json()["push_token"] == ""
        assert response.json()["push_token_configured"] is True
        assert response.json()["push_server_url"] == "http://192.168.1.20:8767"
        assert len(TrackingRouter.instances) == 1
        assert original.stopped is False
        assert store.load().push_token == "local-secret"


def test_web_recording_controls_create_a_session(tmp_path: Path) -> None:
    TrackingRouter.instances.clear()
    store = SettingsStore(tmp_path / "config.json")
    app = create_web_app(
        settings_store=store,
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        router_factory=TrackingRouter,
    )

    with TestClient(app) as client:
        initial = client.get("/api/recording").json()
        assert initial["recording"] is False
        assert initial["sessions_dir"] == str((tmp_path / "sessions").resolve())

        started = client.post("/api/recording/start", json={})
        assert started.status_code == 200
        assert started.json()["recording"] is True
        session_id = started.json()["session_id"]

        event = MidiEvent.from_raw(
            seq=1,
            captured_monotonic_ns=perf_counter_ns(),
            source_port="test",
            raw=[0x90, 60, 90],
        )
        assert app.state.dispatcher.publish_nowait(event)

        stopped = client.post(
            "/api/recording/stop",
            json={"save_name": "Web Test"},
        )
        assert stopped.status_code == 200
        result = stopped.json()["result"]
        assert result["session_id"] == session_id
        assert result["event_count"] == 1
        assert result["complete"] is True
        assert result["save_name"] == "Web Test"
        assert result["discarded"] is False

        discarded_start = client.post("/api/recording/start", json={}).json()
        discarded_id = discarded_start["session_id"]
        discarded = client.post(
            "/api/recording/stop",
            json={"discard": True},
        )
        assert discarded.status_code == 200
        assert discarded.json()["result"]["discarded"] is True
        assert discarded.json()["result"]["directory"] is None
        assert not (tmp_path / "sessions" / discarded_id).exists()

        client.post("/api/recording/start", json={})
        invalid = client.post(
            "/api/recording/stop",
            json={"save_name": "../outside"},
        )
        assert invalid.status_code == 409
        assert client.get("/api/recording").json()["recording"] is True
        assert client.post(
            "/api/recording/stop",
            json={"discard": True},
        ).status_code == 200

    session_dir = tmp_path / "sessions" / "Web Test"
    assert (session_dir / "events.jsonl").is_file()
    assert (session_dir / "session.json").is_file()
    assert (session_dir / "summary.json").is_file()
    assert (session_dir / "session.mid").is_file()
    assert not (tmp_path / "sessions" / session_id).exists()


def test_web_recording_requires_a_running_midi_route(tmp_path: Path) -> None:
    app = create_web_app(
        settings_store=SettingsStore(tmp_path / "config.json"),
        virtual_status_provider=available_driver,
        midi_ports_provider=available_ports,
        auto_start_midi=False,
    )
    with TestClient(app) as client:
        response = client.post("/api/recording/start", json={})
        assert response.status_code == 409
        assert "启动 MIDI 路由" in response.json()["detail"]
