from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image
import pystray


WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_SIZE = 0x0005
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETFONT = 0x0030
WM_SETICON = 0x0080
WM_APP = 0x8000
WM_APP_SHOW = WM_APP + 1
WM_APP_EXIT = WM_APP + 2

SIZE_MINIMIZED = 1
SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_TABSTOP = 0x00010000
WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
BS_PUSHBUTTON = 0x00000000
SS_LEFT = 0x00000000

COLOR_WINDOW = 5
DEFAULT_GUI_FONT = 17
IMAGE_ICON = 1
ICON_SMALL = 0
ICON_BIG = 1
LR_LOADFROMFILE = 0x00000010
EXIT_BUTTON_ID = 1001
ACTION_TIMER_ID = 1

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
MAXIMUM_ALLOWED = 0x02000000
SECURITY_IMPERSONATION = 2
TOKEN_PRIMARY = 1
LOGON_WITH_PROFILE = 0x00000001
CREATE_UNICODE_ENVIRONMENT = 0x00000400

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    )


class STARTUPINFOW(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    )


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    )


def runtime_asset_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS"))
    else:
        root = Path(__file__).resolve().parents[1]
    return root / "assets" / name


def configure_windows_app_identity() -> None:
    setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [wintypes.LPCWSTR]
    setter.restype = ctypes.HRESULT
    setter("PianoTelemetry.Desktop")


def webui_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}/"


def open_webui_unelevated(url: str) -> None:
    """Open a URL with the desktop shell token, even when this app is elevated."""
    try:
        _open_with_explorer_token(url)
    except OSError:
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = wintypes.HINSTANCE
        result = shell32.ShellExecuteW(None, "open", url, None, None, SW_SHOW)
        if int(result or 0) <= 32:
            raise ctypes.WinError()


def _open_with_explorer_token(url: str) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.DuplicateTokenEx.restype = wintypes.BOOL
    advapi32.CreateProcessWithTokenW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL

    shell_window = user32.FindWindowW("Shell_TrayWnd", None)
    if not shell_window:
        raise ctypes.WinError()
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(shell_window, ctypes.byref(process_id))
    if not process_id.value:
        raise ctypes.WinError()

    process = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        process_id.value,
    )
    if not process:
        raise ctypes.WinError()

    token = wintypes.HANDLE()
    primary_token = wintypes.HANDLE()
    process_info = PROCESS_INFORMATION()
    try:
        if not advapi32.OpenProcessToken(
            process,
            TOKEN_QUERY | TOKEN_DUPLICATE,
            ctypes.byref(token),
        ):
            raise ctypes.WinError()
        if not advapi32.DuplicateTokenEx(
            token,
            MAXIMUM_ALLOWED,
            None,
            SECURITY_IMPERSONATION,
            TOKEN_PRIMARY,
            ctypes.byref(primary_token),
        ):
            raise ctypes.WinError()

        explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
        command = ctypes.create_unicode_buffer(f'"{explorer}" "{url}"')
        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(STARTUPINFOW)
        if not advapi32.CreateProcessWithTokenW(
            primary_token,
            LOGON_WITH_PROFILE,
            None,
            command,
            CREATE_UNICODE_ENVIRONMENT,
            None,
            None,
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            raise ctypes.WinError()
    finally:
        for handle in (
            process_info.hThread,
            process_info.hProcess,
            primary_token,
            token,
            process,
        ):
            if handle:
                kernel32.CloseHandle(handle)


def _configure_win32() -> tuple[object, object, object]:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = LRESULT
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.MessageBoxW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.UINT,
    ]
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.GetStockObject.restype = wintypes.HANDLE
    return user32, kernel32, gdi32


class WindowsTrayIcon:
    def __init__(self, image_path: Path, actions: queue.SimpleQueue[str]) -> None:
        self.actions = actions
        with Image.open(image_path) as source:
            image = source.convert("RGBA")
            image.load()
        menu = pystray.Menu(
            pystray.MenuItem(
                "显示",
                self._show_window,
                default=True,
                visible=False,
            ),
            pystray.MenuItem("退出", self._exit),
        )
        self.icon = pystray.Icon(
            "PianoTelemetry",
            image,
            "Piano Telemetry",
            menu,
        )
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None

    def _show_window(self, _icon, _item) -> None:
        self.actions.put("show")

    def _exit(self, _icon, _item) -> None:
        self.actions.put("exit")

    def _run(self) -> None:
        try:
            self.icon.run()
        except BaseException as exc:
            self.error = exc

    def start(self, timeout: float = 5.0) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name="piano-tray",
            daemon=True,
        )
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.icon.visible:
                return
            if self.error is not None or not self.thread.is_alive():
                break
            time.sleep(0.05)
        detail = str(self.error) if self.error else "创建通知栏图标超时"
        raise RuntimeError(detail)

    def stop(self, timeout: float = 3.0) -> None:
        self.icon.stop()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)


class DesktopWebServer:
    def __init__(self, host: str, port: int) -> None:
        import uvicorn

        from piano_telemetry.web_server import create_web_app

        config = uvicorn.Config(
            create_web_app(),
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            ws="websockets-sansio",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self._run,
            name="piano-web-server",
            daemon=True,
        )
        self.error: BaseException | None = None

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:
            self.error = exc

    def start(self, timeout: float = 10.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if self.error is not None or not self.thread.is_alive():
                break
            time.sleep(0.05)
        detail = str(self.error) if self.error else "Web 服务未能启动"
        raise RuntimeError(detail)

    def request_stop(self) -> None:
        self.server.should_exit = True


class NativeControlWindow:
    def __init__(
        self,
        *,
        port: int,
        icon_path: Path,
        actions: queue.SimpleQueue[str],
        on_exit,
    ) -> None:
        self.port = port
        self.icon_path = icon_path
        self.actions = actions
        self.on_exit = on_exit
        self.user32, self.kernel32, self.gdi32 = _configure_win32()
        self.hinstance = self.kernel32.GetModuleHandleW(None)
        self.class_name = f"PianoTelemetryControl_{os.getpid()}"
        self.hwnd: int | None = None
        self.large_icon: int | None = None
        self.small_icon: int | None = None
        self._window_proc_ref = WNDPROC(self._window_proc)
        self._register_and_create()

    def _load_icon(self, size: int) -> int | None:
        return self.user32.LoadImageW(
            None,
            str(self.icon_path),
            IMAGE_ICON,
            size,
            size,
            LR_LOADFROMFILE,
        )

    def _register_and_create(self) -> None:
        self.large_icon = self._load_icon(32)
        self.small_icon = self._load_icon(16)
        window_class = WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = self._window_proc_ref
        window_class.hInstance = self.hinstance
        window_class.hIcon = self.large_icon
        window_class.hIconSm = self.small_icon
        window_class.hbrBackground = COLOR_WINDOW + 1
        window_class.lpszClassName = self.class_name
        if not self.user32.RegisterClassExW(ctypes.byref(window_class)):
            raise ctypes.WinError()

        width, height = 360, 160
        x = max(0, (self.user32.GetSystemMetrics(0) - width) // 2)
        y = max(0, (self.user32.GetSystemMetrics(1) - height) // 2)
        style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
        hwnd = self.user32.CreateWindowExW(
            0,
            self.class_name,
            "Piano Telemetry",
            style,
            x,
            y,
            width,
            height,
            None,
            None,
            self.hinstance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError()
        self.hwnd = hwnd
        self.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, self.large_icon or 0)
        self.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, self.small_icon or 0)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_CREATE:
            self._create_controls(hwnd)
            self.user32.SetTimer(hwnd, ACTION_TIMER_ID, 80, None)
            return 0
        if message == WM_COMMAND and (int(wparam) & 0xFFFF) == EXIT_BUTTON_ID:
            self.on_exit()
            return 0
        if message == WM_TIMER and int(wparam) == ACTION_TIMER_ID:
            self._process_actions()
            return 0
        if message == WM_APP_SHOW:
            self.show()
            return 0
        if message == WM_APP_EXIT:
            self.on_exit()
            return 0
        if message == WM_SIZE and int(wparam) == SIZE_MINIMIZED:
            self.hide()
            return 0
        if message == WM_CLOSE:
            self.hide()
            return 0
        if message == WM_DESTROY:
            self.user32.KillTimer(hwnd, ACTION_TIMER_ID)
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _create_controls(self, hwnd: int) -> None:
        font = self.gdi32.GetStockObject(DEFAULT_GUI_FONT)
        label = self.user32.CreateWindowExW(
            0,
            "STATIC",
            f"WebUI端口：{self.port}",
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            24,
            28,
            300,
            24,
            hwnd,
            None,
            self.hinstance,
            None,
        )
        button = self.user32.CreateWindowExW(
            0,
            "BUTTON",
            "退出",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            250,
            78,
            80,
            30,
            hwnd,
            wintypes.HMENU(EXIT_BUTTON_ID),
            self.hinstance,
            None,
        )
        if label:
            self.user32.SendMessageW(label, WM_SETFONT, font, 1)
        if button:
            self.user32.SendMessageW(button, WM_SETFONT, font, 1)

    def _process_actions(self) -> None:
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                return
            if action == "show":
                self.show()
            elif action == "exit":
                self.on_exit()
                return

    def run(self) -> None:
        message = wintypes.MSG()
        while True:
            result = self.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def show(self) -> None:
        if not self.hwnd:
            return
        self.user32.ShowWindow(self.hwnd, SW_RESTORE)
        self.user32.ShowWindow(self.hwnd, SW_SHOW)
        self.user32.SetForegroundWindow(self.hwnd)

    def hide(self) -> None:
        if self.hwnd:
            self.user32.ShowWindow(self.hwnd, SW_HIDE)

    def destroy(self) -> None:
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def show_error(self, detail: str) -> None:
        self.user32.MessageBoxW(
            self.hwnd,
            f"启动失败：{detail}",
            "Piano Telemetry",
            0x10,
        )

    def close(self) -> None:
        self.destroy()
        self.user32.UnregisterClassW(self.class_name, self.hinstance)
        if self.large_icon:
            self.user32.DestroyIcon(self.large_icon)
        if self.small_icon:
            self.user32.DestroyIcon(self.small_icon)


class WindowsDesktopApp:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        browser_opener=open_webui_unelevated,
    ) -> None:
        self.host = host
        self.port = port
        self.actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.server = DesktopWebServer(host, port)
        self.browser_opener = browser_opener
        self.tray = WindowsTrayIcon(
            runtime_asset_path("piano-emoji.ico"),
            self.actions,
        )
        self.exiting = False
        self.window = NativeControlWindow(
            port=port,
            icon_path=runtime_asset_path("piano-emoji.ico"),
            actions=self.actions,
            on_exit=self.begin_exit,
        )

    def run(self) -> int:
        try:
            self.server.start()
            self.tray.start()
        except Exception as exc:
            self.server.request_stop()
            if self.server.thread.is_alive():
                self.server.thread.join(3.0)
            self.window.show_error(str(exc))
            self.window.close()
            return 2

        try:
            self.browser_opener(webui_url(self.host, self.port))
        except OSError:
            # Browser launch is a convenience and must not stop MIDI routing.
            pass

        self.window.run()
        self.window.close()
        return 0

    def begin_exit(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.window.hide()
        self.tray.stop()
        self.server.request_stop()
        self.server.thread.join(8.0)
        if self.server.thread.is_alive():
            self.server.server.force_exit = True
            self.server.thread.join(1.0)
        self.window.destroy()


def run_windows_desktop(*, host: str = "127.0.0.1", port: int = 8765) -> int:
    if os.name != "nt":
        raise RuntimeError("桌面托盘模式仅支持 Windows")
    configure_windows_app_identity()
    return WindowsDesktopApp(host=host, port=port).run()
