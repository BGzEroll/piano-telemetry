from __future__ import annotations

import asyncio
import shutil
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from threading import Timer

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from piano_telemetry.analyzer.tonality import (
    DEFAULT_TONALITY,
    normalize_tonality,
    tonalities_payload,
)
from piano_telemetry.core.config import AppSettings, SettingsStore
from piano_telemetry.core.controller import MidiController
from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.core.key_mapping import (
    ALLOWED_KEY_CODES,
    PIANO_NOTE_MAX,
    PIANO_NOTE_MIN,
    KeyboardMappingService,
    KeyboardMappingSettings,
    KeyboardMappingStore,
)
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.ports import list_midi_ports
from piano_telemetry.midi.router import MidiRouter
from piano_telemetry.midi.virtual_midi import (
    VIRTUAL_INPUT_PORT_NAME,
    VIRTUAL_OUTPUT_PORT_NAME,
    virtual_midi_status,
)
from piano_telemetry.recorder.session_recorder import (
    SessionRecorder,
    SessionResult,
    SessionState,
)
from piano_telemetry.web_hub import WebEventHub


class SettingsPayload(BaseModel):
    input_port: str = VIRTUAL_INPUT_PORT_NAME
    tonality: str = DEFAULT_TONALITY
    receive_sysex: bool = False
    receive_clock: bool = False
    receive_active_sensing: bool = False
    panic_on_stop: bool = True


class RecordingStartPayload(BaseModel):
    piece: str | None = Field(default=None, max_length=200)
    target_bpm: float | None = Field(default=None, gt=0, le=400)


class TonalityPayload(BaseModel):
    tonality: str = DEFAULT_TONALITY


class RecordingStopPayload(BaseModel):
    save_name: str | None = Field(default=None, max_length=100)
    discard: bool = False


class KeyboardMappingPayload(BaseModel):
    enabled: bool = False
    bindings: dict[str, str] = Field(default_factory=dict)


def create_web_app(
    *,
    settings_store: SettingsStore | None = None,
    dispatcher: EventDispatcher[MidiEvent] | None = None,
    virtual_status_provider=virtual_midi_status,
    midi_ports_provider=list_midi_ports,
    router_factory=MidiRouter,
    recorder: SessionRecorder | None = None,
    keyboard_mapping_store: KeyboardMappingStore | None = None,
    keyboard_mapper: KeyboardMappingService | None = None,
    auto_start_midi: bool = True,
):
    store = settings_store or SettingsStore()
    event_dispatcher = dispatcher or EventDispatcher[MidiEvent](ingress_capacity=4096)
    mapping_store = keyboard_mapping_store or KeyboardMappingStore(
        store.path.parent / "key_mapping.json"
    )
    mapper = keyboard_mapper or KeyboardMappingService(mapping_store)
    controller = MidiController(
        event_dispatcher,
        router_factory=router_factory,
        status_provider=virtual_status_provider,
        keyboard_mapper=mapper,
    )
    hub = WebEventHub(event_dispatcher, tonality=store.load().tonality)
    session_recorder = recorder or SessionRecorder(
        event_dispatcher,
        sessions_dir=store.path.parent / "sessions",
    )
    web_root = Path(__file__).resolve().parent / "web"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        event_dispatcher.start()
        hub.start(asyncio.get_running_loop())
        await asyncio.to_thread(session_recorder.start)
        await asyncio.to_thread(mapper.start)
        if auto_start_midi:
            try:
                settings = await asyncio.to_thread(
                    _load_startable_settings,
                    store,
                    midi_ports_provider,
                )
                await asyncio.to_thread(controller.start, settings)
            except Exception:
                # Keep the Web UI available so the user can inspect the error
                # and retry after installing the driver or releasing a port.
                pass
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(controller.stop)
            finally:
                try:
                    await asyncio.to_thread(mapper.stop)
                finally:
                    try:
                        await asyncio.to_thread(session_recorder.close)
                    finally:
                        hub.stop()
                        event_dispatcher.stop(drain=True)

    app = FastAPI(title="Piano Telemetry", version="0.1.0", lifespan=lifespan)
    app.state.settings_store = store
    app.state.dispatcher = event_dispatcher
    app.state.midi_controller = controller
    app.state.web_hub = hub
    app.state.session_recorder = session_recorder
    app.state.keyboard_mapper = mapper

    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(web_root / "visualization.html")

    @app.get("/visualization", include_in_schema=False)
    async def visualization():
        return FileResponse(web_root / "visualization.html")

    @app.get("/settings", include_in_schema=False)
    async def settings_page():
        return FileResponse(web_root / "settings.html")

    @app.get("/mapping", include_in_schema=False)
    async def mapping_page():
        return FileResponse(web_root / "mapping.html")

    @app.get("/api/settings")
    async def get_settings() -> dict[str, object]:
        return store.load().to_dict()

    @app.put("/api/settings")
    async def put_settings(payload: SettingsPayload) -> dict[str, object]:
        try:
            settings, restarted = await asyncio.to_thread(
                _save_and_apply_settings,
                store,
                controller,
                AppSettings.from_dict(payload.model_dump()),
                midi_ports_provider,
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        result = settings.to_dict()
        hub.set_tonality(settings.tonality)
        result["midi_restarted"] = restarted
        return result

    @app.get("/api/key-mapping")
    async def get_key_mapping() -> dict[str, object]:
        result = mapper.status()
        result.update(
            {
                "allowed_keys": list(ALLOWED_KEY_CODES),
                "note_min": PIANO_NOTE_MIN,
                "note_max": PIANO_NOTE_MAX,
            }
        )
        return result

    @app.put("/api/key-mapping")
    async def put_key_mapping(payload: KeyboardMappingPayload) -> dict[str, object]:
        try:
            settings = KeyboardMappingSettings.from_dict(
                payload.model_dump(),
                strict=True,
            )
            await asyncio.to_thread(mapper.apply, settings)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return mapper.status()

    @app.get("/api/tonality")
    async def get_tonality() -> dict[str, object]:
        return {
            "tonality": store.load().tonality,
            "options": tonalities_payload(),
        }

    @app.put("/api/tonality")
    async def put_tonality(payload: TonalityPayload) -> dict[str, object]:
        selected = normalize_tonality(payload.tonality)
        if selected != payload.tonality:
            raise HTTPException(status_code=422, detail="不支持的调式")
        settings = replace(store.load(), tonality=selected)
        await asyncio.to_thread(store.save, settings)
        return {
            "tonality": selected,
            "state": hub.set_tonality(selected),
        }

    @app.get("/api/midi/ports")
    async def midi_ports() -> dict[str, object]:
        driver_status = await asyncio.to_thread(virtual_status_provider)
        result = driver_status.to_dict()
        try:
            result["inputs"] = await asyncio.to_thread(
                _selectable_input_names,
                midi_ports_provider,
            )
            result["port_scan_error"] = None
        except Exception as exc:
            result["inputs"] = [VIRTUAL_INPUT_PORT_NAME]
            result["port_scan_error"] = str(exc)
        return result

    @app.post("/api/midi/start")
    async def start_midi() -> dict[str, object]:
        try:
            settings = await asyncio.to_thread(
                _load_startable_settings,
                store,
                midi_ports_provider,
            )
            return await asyncio.to_thread(controller.start, settings)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/midi/stop")
    async def stop_midi() -> dict[str, object]:
        result = await asyncio.to_thread(controller.stop)
        if session_recorder.state is SessionState.RECORDING:
            await asyncio.to_thread(session_recorder.stop_session)
        return result

    @app.get("/api/recording")
    async def recording_status() -> dict[str, object]:
        return session_recorder.status()

    @app.post("/api/recording/start")
    async def start_recording(
        payload: RecordingStartPayload | None = None,
    ) -> dict[str, object]:
        controller_status = await asyncio.to_thread(controller.status)
        if not controller_status["running"]:
            raise HTTPException(status_code=409, detail="请先启动 MIDI 路由")
        details = payload or RecordingStartPayload()
        piece = details.piece.strip() if details.piece else None
        try:
            await asyncio.to_thread(
                session_recorder.start_session,
                piece=piece or None,
                target_bpm=details.target_bpm,
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session_recorder.status()

    @app.post("/api/recording/stop")
    async def stop_recording(
        choice: RecordingStopPayload | None = None,
    ) -> dict[str, object]:
        selection = choice or RecordingStopPayload()
        if selection.discard and selection.save_name:
            raise HTTPException(
                status_code=409,
                detail="保存名称和不保存不能同时选择",
            )
        save_name: str | None = None
        try:
            if selection.save_name is not None:
                save_name = _validate_recording_save_name(selection.save_name)
                target = session_recorder.sessions_dir / save_name
                if target.exists():
                    raise ValueError("保存名称已存在，请换一个名称")
            result = await asyncio.to_thread(session_recorder.stop_session)
            if selection.discard:
                await asyncio.to_thread(
                    _discard_recording_directory,
                    result,
                    session_recorder.sessions_dir,
                )
            elif save_name is not None:
                result = await asyncio.to_thread(
                    _rename_recording_directory,
                    result,
                    session_recorder.sessions_dir,
                    save_name,
                )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload = session_recorder.status()
        payload["result"] = _recording_result_payload(
            result,
            discarded=selection.discard,
            save_name=save_name,
        )
        return payload

    @app.get("/api/status")
    async def status() -> dict[str, object]:
        result = controller.status()
        result["websocket_clients"] = hub.client_count
        result["websocket_drop_total"] = hub.client_drop_total
        result["config_path"] = str(store.path)
        result["recording"] = session_recorder.status()
        result["key_mapping"] = mapper.status()
        return result

    @app.get("/api/state")
    async def current_state() -> dict[str, object]:
        return hub.latest_state()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = hub.register()
        try:
            await websocket.send_json(hub.latest_state())
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except TimeoutError:
                    await websocket.send_json({"kind": "ping"})
                    continue
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(queue)

    return app


def _matches_managed_port(name: str, managed_name: str) -> bool:
    folded = name.casefold()
    managed = managed_name.casefold()
    return folded == managed or folded.startswith(f"{managed} ")


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _validate_recording_save_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("请输入保存名称")
    if name in {".", ".."} or name.endswith("."):
        raise ValueError("保存名称无效")
    if any(ord(character) < 32 or character in '<>:"/\\|?*' for character in name):
        raise ValueError("保存名称包含 Windows 文件夹不支持的字符")
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("保存名称是 Windows 保留名称")
    return name


def _recording_source_directory(
    result: SessionResult,
    sessions_dir: Path,
) -> tuple[Path, Path]:
    root = sessions_dir.resolve()
    source = result.directory.resolve()
    if source.parent != root or not source.is_dir():
        raise RuntimeError("录制目录不在预期位置，已拒绝文件操作")
    return root, source


def _rename_recording_directory(
    result: SessionResult,
    sessions_dir: Path,
    save_name: str,
) -> SessionResult:
    root, source = _recording_source_directory(result, sessions_dir)
    target = root / save_name
    if target.exists():
        raise ValueError("保存名称已存在，请换一个名称")
    source.rename(target)
    return replace(result, directory=target)


def _discard_recording_directory(
    result: SessionResult,
    sessions_dir: Path,
) -> None:
    _, source = _recording_source_directory(result, sessions_dir)
    shutil.rmtree(source)


def _recording_result_payload(
    result: SessionResult,
    *,
    discarded: bool = False,
    save_name: str | None = None,
) -> dict[str, object]:
    return {
        "session_id": result.session_id,
        "directory": None if discarded else str(result.directory.resolve()),
        "save_name": save_name,
        "discarded": discarded,
        "complete": result.complete,
        "event_count": result.event_count,
        "sequence_gap_events": result.sequence_gap_events,
        "ingress_dropped_events": result.ingress_dropped_events,
        "subscriber_dropped_events": result.subscriber_dropped_events,
        "midi_exported_events": result.midi_exported_events,
        "midi_skipped_events": result.midi_skipped_events,
        "midi_export_error": result.midi_export_error,
    }


def _selectable_input_names(midi_ports_provider) -> list[str]:
    discovered = midi_ports_provider()
    selectable_inputs = [VIRTUAL_INPUT_PORT_NAME]
    for name in discovered.inputs:
        if _matches_managed_port(name, VIRTUAL_OUTPUT_PORT_NAME):
            continue
        if name not in selectable_inputs:
            selectable_inputs.append(name)
    return selectable_inputs


def _load_startable_settings(
    store: SettingsStore,
    midi_ports_provider,
) -> AppSettings:
    settings = store.load()
    try:
        inputs = _selectable_input_names(midi_ports_provider)
    except Exception:
        inputs = [VIRTUAL_INPUT_PORT_NAME]

    selected = next(
        (
            name
            for name in inputs
            if name.casefold() == settings.input_port.casefold()
        ),
        VIRTUAL_INPUT_PORT_NAME,
    )
    if selected != settings.input_port:
        settings = replace(settings, input_port=selected)
        store.save(settings)
    return settings


def _save_and_apply_settings(
    store: SettingsStore,
    controller: MidiController,
    settings: AppSettings,
    midi_ports_provider,
) -> tuple[AppSettings, bool]:
    was_running = bool(controller.status()["running"])
    store.save(settings)
    settings = _load_startable_settings(store, midi_ports_provider)
    if was_running:
        controller.stop()
        controller.start(settings)
    return settings, was_running


def run_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    import uvicorn

    if open_browser:
        browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        timer = Timer(0.8, webbrowser.open, args=(f"http://{browser_host}:{port}/",))
        timer.daemon = True
        timer.start()
    uvicorn.run(
        create_web_app(),
        host=host,
        port=port,
        log_level="info",
        ws="websockets-sansio",
    )
