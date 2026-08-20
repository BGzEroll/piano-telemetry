from __future__ import annotations

import asyncio
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Timer

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from piano_telemetry.core.config import AppSettings, SettingsStore
from piano_telemetry.core.controller import MidiController
from piano_telemetry.core.dispatcher import EventDispatcher
from piano_telemetry.midi.event import MidiEvent
from piano_telemetry.midi.ports import list_midi_ports
from piano_telemetry.web_hub import WebEventHub


class SettingsPayload(BaseModel):
    input_port: str | None = None
    output_port: str | None = None
    receive_sysex: bool = False
    receive_clock: bool = False
    receive_active_sensing: bool = False
    panic_on_stop: bool = True


def create_web_app(
    *,
    settings_store: SettingsStore | None = None,
    dispatcher: EventDispatcher[MidiEvent] | None = None,
):
    store = settings_store or SettingsStore()
    event_dispatcher = dispatcher or EventDispatcher[MidiEvent](ingress_capacity=4096)
    controller = MidiController(event_dispatcher)
    hub = WebEventHub(event_dispatcher)
    web_root = Path(__file__).resolve().parent / "web"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        event_dispatcher.start()
        hub.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            await asyncio.to_thread(controller.stop)
            hub.stop()
            event_dispatcher.stop(drain=True)

    app = FastAPI(title="Piano Telemetry", version="0.1.0", lifespan=lifespan)
    app.state.settings_store = store
    app.state.dispatcher = event_dispatcher
    app.state.midi_controller = controller
    app.state.web_hub = hub

    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")

    @app.get("/", include_in_schema=False)
    async def portal():
        return FileResponse(web_root / "portal.html")

    @app.get("/visualization", include_in_schema=False)
    async def visualization():
        return FileResponse(web_root / "visualization.html")

    @app.get("/settings", include_in_schema=False)
    async def settings_page():
        return FileResponse(web_root / "settings.html")

    @app.get("/api/settings")
    async def get_settings() -> dict[str, object]:
        return store.load().to_dict()

    @app.put("/api/settings")
    async def put_settings(payload: SettingsPayload) -> dict[str, object]:
        settings = AppSettings.from_dict(payload.model_dump())
        await asyncio.to_thread(store.save, settings)
        return settings.to_dict()

    @app.get("/api/midi/ports")
    async def midi_ports() -> dict[str, list[str]]:
        try:
            ports = await asyncio.to_thread(list_midi_ports)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"inputs": list(ports.inputs), "outputs": list(ports.outputs)}

    @app.post("/api/midi/start")
    async def start_midi() -> dict[str, object]:
        try:
            return await asyncio.to_thread(controller.start, store.load())
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/midi/stop")
    async def stop_midi() -> dict[str, object]:
        return await asyncio.to_thread(controller.stop)

    @app.get("/api/status")
    async def status() -> dict[str, object]:
        result = controller.status()
        result["websocket_clients"] = hub.client_count
        result["websocket_drop_total"] = hub.client_drop_total
        result["config_path"] = str(store.path)
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
