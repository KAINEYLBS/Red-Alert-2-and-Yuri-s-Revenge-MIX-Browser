"""Write release workflow status messages with console emphasis colors."""

from __future__ import annotations

import os
import sys
from typing import TextIO


_WINDOWS_ATTRIBUTES = {"red": 0x0C, "green": 0x0A, "yellow": 0x0E}
_ANSI_CODES = {"red": "\x1b[91m", "green": "\x1b[92m", "yellow": "\x1b[93m"}


# @arch ra2ayrmb.release-console-status utility | en: Prints colored release status messages | zh: 使用强调色输出发布状态信息
def write_status(message: str, color: str, *, stream: TextIO | None = None) -> None:
    output = stream or sys.stdout
    normalized_color = color.casefold()
    if normalized_color not in _WINDOWS_ATTRIBUTES:
        raise ValueError(f"Unsupported release status color: {color}")

    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class Coord(ctypes.Structure):
                _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

            class SmallRect(ctypes.Structure):
                _fields_ = [
                    ("Left", wintypes.SHORT),
                    ("Top", wintypes.SHORT),
                    ("Right", wintypes.SHORT),
                    ("Bottom", wintypes.SHORT),
                ]

            class ConsoleScreenBufferInfo(ctypes.Structure):
                _fields_ = [
                    ("dwSize", Coord),
                    ("dwCursorPosition", Coord),
                    ("wAttributes", wintypes.WORD),
                    ("srWindow", SmallRect),
                    ("dwMaximumWindowSize", Coord),
                ]

            handle = msvcrt.get_osfhandle(output.fileno())
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            info = ConsoleScreenBufferInfo()
            get_info = kernel32.GetConsoleScreenBufferInfo
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ConsoleScreenBufferInfo)]
            get_info.restype = wintypes.BOOL
            set_attributes = kernel32.SetConsoleTextAttribute
            set_attributes.argtypes = [wintypes.HANDLE, wintypes.WORD]
            set_attributes.restype = wintypes.BOOL
            if get_info(handle, ctypes.byref(info)):
                try:
                    color_attributes = (
                        info.wAttributes & 0xF0
                    ) | _WINDOWS_ATTRIBUTES[normalized_color]
                    set_attributes(handle, color_attributes)
                    print(message, file=output)
                finally:
                    set_attributes(handle, info.wAttributes)
                return
        except (AttributeError, OSError, ValueError):
            pass
    elif output.isatty():
        print(f"{_ANSI_CODES[normalized_color]}{message}\x1b[0m", file=output)
        return

    print(message, file=output)
