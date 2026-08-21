from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Sequence


VIRTUAL_INPUT_PORT_NAME = "Piano Telemetry Input"
VIRTUAL_OUTPUT_PORT_NAME = "Piano Telemetry Output"
VIRTUAL_MIDI_INSTALL_URL = "https://www.tobias-erichsen.de/software/loopmidi.html"

_PARSE_RX = 0x01
_INSTANTIATE_RX_ONLY = 0x04
_INSTANTIATE_TX_ONLY = 0x08
_MAX_SYSEX_LENGTH = 0xFFFF

MidiCallback = Callable[[list[int]], None]
_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_NATIVE_CALLBACK = _CALLBACK_FACTORY(
    None,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_uint32,
    ctypes.c_size_t,
)


class VirtualMidiUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VirtualMidiStatus:
    available: bool
    input_port: str = VIRTUAL_INPUT_PORT_NAME
    output_port: str = VIRTUAL_OUTPUT_PORT_NAME
    install_url: str = VIRTUAL_MIDI_INSTALL_URL
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def virtual_midi_dll_path() -> Path:
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return windows_root / "System32" / "teVirtualMIDI.dll"


def virtual_midi_status() -> VirtualMidiStatus:
    if sys.platform != "win32":
        return VirtualMidiStatus(
            available=False,
            message="驱动未就绪，teVirtualMIDI 仅支持 Windows。",
        )
    path = virtual_midi_dll_path()
    if not path.is_file():
        return VirtualMidiStatus(
            available=False,
            message="驱动未就绪，请先安装 loopMIDI 后重启程序。",
        )
    try:
        VirtualMidiDriver()
    except (OSError, AttributeError) as exc:
        return VirtualMidiStatus(
            available=False,
            message=f"驱动未就绪，teVirtualMIDI 无法加载：{exc}",
        )
    return VirtualMidiStatus(
        available=True,
        message="驱动已就绪，端口将在启动 MIDI 时创建。",
    )


class VirtualMidiDriver:
    """Thin ctypes binding; the third-party DLL must already be installed."""

    def __init__(self, dll: object | None = None) -> None:
        if dll is None:
            if sys.platform != "win32" or not hasattr(ctypes, "WinDLL"):
                raise OSError("teVirtualMIDI is only available on Windows")
            path = virtual_midi_dll_path()
            if not path.is_file():
                raise OSError(f"teVirtualMIDI.dll not found: {path}")
            dll = ctypes.WinDLL(str(path), use_last_error=True)  # type: ignore[attr-defined]
        self._dll = dll
        self._bind_functions()

    def _bind_functions(self) -> None:
        self._create = self._dll.virtualMIDICreatePortEx2
        self._create.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_uint32,
        )
        self._create.restype = ctypes.c_void_p

        self._close = self._dll.virtualMIDIClosePort
        self._close.argtypes = (ctypes.c_void_p,)
        self._close.restype = None

        self._send = self._dll.virtualMIDISendData
        self._send.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint32,
        )
        self._send.restype = ctypes.c_int

    def create_input_port(
        self,
        name: str,
        callback: MidiCallback,
    ) -> VirtualMidiInputPort:
        return VirtualMidiInputPort(self, name, callback)

    def create_output_port(self, name: str) -> VirtualMidiOutputPort:
        return VirtualMidiOutputPort(self, name)

    def _create_port(
        self,
        name: str,
        *,
        callback: object | None,
        flags: int,
    ) -> int:
        callback_pointer = (
            ctypes.cast(callback, ctypes.c_void_p) if callback is not None else None
        )
        handle = self._create(
            name,
            callback_pointer,
            0,
            _MAX_SYSEX_LENGTH,
            flags,
        )
        if not handle:
            error = ctypes.get_last_error()
            detail = ctypes.FormatError(error).strip() if error else "未知错误"
            raise RuntimeError(f"无法创建虚拟 MIDI 端口 {name!r}：{detail}")
        return int(handle)

    def _close_port(self, handle: int) -> None:
        self._close(ctypes.c_void_p(handle))

    def _send_message(self, handle: int, message: Sequence[int]) -> None:
        if not message:
            return
        if any(not 0 <= value <= 0xFF for value in message):
            raise ValueError("MIDI bytes must be in the range 0..255")
        buffer = (ctypes.c_ubyte * len(message))(*message)
        if not self._send(ctypes.c_void_p(handle), buffer, len(message)):
            error = ctypes.get_last_error()
            detail = ctypes.FormatError(error).strip() if error else "未知错误"
            raise RuntimeError(f"发送虚拟 MIDI 数据失败：{detail}")


class _VirtualMidiPort:
    def __init__(self, driver: VirtualMidiDriver, name: str) -> None:
        self._driver = driver
        self.name = name
        self._handle: int | None = None
        self._lock = RLock()

    def close_port(self) -> None:
        with self._lock:
            handle = self._handle
            self._handle = None
        if handle is not None:
            self._driver._close_port(handle)

    def cancel_callback(self) -> None:
        # The native callback stops when close_port releases the driver handle.
        return None

    def __del__(self) -> None:
        try:
            self.close_port()
        except Exception:
            pass


class VirtualMidiInputPort(_VirtualMidiPort):
    def __init__(
        self,
        driver: VirtualMidiDriver,
        name: str,
        callback: MidiCallback,
    ) -> None:
        super().__init__(driver, name)
        self._callback = callback

        def native_callback(
            _port: object,
            data: ctypes.POINTER(ctypes.c_ubyte),
            length: int,
            _instance: int,
        ) -> None:
            if not data or length <= 0:
                return
            try:
                self._callback(list(data[:length]))
            except Exception:
                # Never let Python exceptions escape through a native callback.
                return

        self._native_callback = _NATIVE_CALLBACK(native_callback)
        self._handle = driver._create_port(
            name,
            callback=self._native_callback,
            flags=_INSTANTIATE_RX_ONLY | _PARSE_RX,
        )


class VirtualMidiOutputPort(_VirtualMidiPort):
    def __init__(self, driver: VirtualMidiDriver, name: str) -> None:
        super().__init__(driver, name)
        self._handle = driver._create_port(
            name,
            callback=None,
            flags=_INSTANTIATE_TX_ONLY,
        )

    def send_message(self, message: Sequence[int]) -> None:
        with self._lock:
            handle = self._handle
            if handle is None:
                raise RuntimeError("虚拟 MIDI 输出端口未打开")
            self._driver._send_message(handle, message)
