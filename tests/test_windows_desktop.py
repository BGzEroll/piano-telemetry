import queue

from piano_telemetry.windows_desktop import WindowsTrayIcon, runtime_asset_path


def test_desktop_assets_exist_and_tray_menu_only_exposes_exit() -> None:
    image_path = runtime_asset_path("piano-emoji.ico")
    assert image_path.is_file()

    tray = WindowsTrayIcon(image_path, queue.SimpleQueue())
    visible_items = [item.text for item in tray.icon.menu if item.visible]
    assert visible_items == ["退出"]
