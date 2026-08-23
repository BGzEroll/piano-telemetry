import queue

from piano_telemetry.windows_desktop import (
    WindowsTrayIcon,
    runtime_asset_path,
    webui_url,
)


def test_desktop_assets_exist_and_tray_menu_only_exposes_exit() -> None:
    image_path = runtime_asset_path("piano-emoji.ico")
    assert image_path.is_file()

    tray = WindowsTrayIcon(image_path, queue.SimpleQueue())
    visible_items = [item.text for item in tray.icon.menu if item.visible]
    assert visible_items == ["退出"]


def test_webui_url_uses_loopback_for_wildcard_hosts() -> None:
    assert webui_url("127.0.0.1", 8765) == "http://127.0.0.1:8765/"
    assert webui_url("0.0.0.0", 9000) == "http://127.0.0.1:9000/"


def test_packaged_app_requests_administrator_privileges() -> None:
    spec = runtime_asset_path("piano-emoji.ico").parents[1] / "PianoTelemetry.spec"
    assert "uac_admin=True" in spec.read_text(encoding="utf-8")
