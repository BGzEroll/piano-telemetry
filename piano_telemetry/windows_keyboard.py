from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


class WindowsKeySender:
    """Emit standard A-Z and top-row 0-9 key events through Win32 SendInput."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("键盘映射仅支持 Windows")
        self._user32 = ctypes.windll.user32
        self._user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        self._user32.MapVirtualKeyW.restype = wintypes.UINT
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

    def send(self, key_code: str, *, pressed: bool) -> None:
        virtual_key = _virtual_key(key_code)
        scan_code = self._user32.MapVirtualKeyW(virtual_key, MAPVK_VK_TO_VSC)
        if not scan_code:
            raise RuntimeError(f"无法解析键盘按键：{key_code}")
        flags = KEYEVENTF_SCANCODE
        if not pressed:
            flags |= KEYEVENTF_KEYUP
        event = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )
        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError()


def _virtual_key(key_code: str) -> int:
    if len(key_code) == 4 and key_code.startswith("Key"):
        character = key_code[-1]
    elif len(key_code) == 6 and key_code.startswith("Digit"):
        character = key_code[-1]
    else:
        raise ValueError(f"不支持的键盘按键：{key_code}")
    if character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        raise ValueError(f"不支持的键盘按键：{key_code}")
    return ord(character)
