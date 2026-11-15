"""Console Keystroke Injector for Windows.

Enables injecting prompt text directly into a running interactive agy.exe
console session via Win32 AttachConsole and WriteConsoleInputW APIs.
"""

import ctypes
from ctypes import wintypes
import logging
import time
import psutil
from typing import Optional

logger = logging.getLogger(__name__)

kernel32 = ctypes.windll.kernel32

KEY_EVENT = 0x0001
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("UnicodeChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class INPUT_RECORD_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("Padding", ctypes.c_byte * 16),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wintypes.WORD),
        ("Event", INPUT_RECORD_UNION),
    ]


def find_interactive_agy_pid() -> Optional[int]:
    """Finds the PID of an interactive agy.exe process running locally."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] and "agy" in proc.info["name"].lower():
                cmdline = proc.info.get("cmdline") or []
                # If it's NOT a print-mode headless process (-p / --print)
                if not any(arg in ["-p", "--print", "-h", "--help"] for arg in cmdline):
                    return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def inject_text_to_agy(text: str, pid: Optional[int] = None) -> bool:
    """Injects text + Enter into the interactive agy console window."""
    target_pid = pid or find_interactive_agy_pid()
    if not target_pid:
        logger.warning("No interactive agy process found.")
        return False

    kernel32.FreeConsole()
    if not kernel32.AttachConsole(target_pid):
        logger.warning(f"Failed to AttachConsole to PID {target_pid}: {kernel32.GetLastError()}")
        return False

    try:
        h_conin = kernel32.CreateFileW(
            "CONIN$",
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h_conin == -1 or not h_conin:
            logger.warning("Failed to open CONIN$")
            return False

        records = []
        for ch in text:
            # Key Down
            rec_down = INPUT_RECORD()
            rec_down.EventType = KEY_EVENT
            rec_down.Event.KeyEvent.bKeyDown = True
            rec_down.Event.KeyEvent.wRepeatCount = 1
            rec_down.Event.KeyEvent.UnicodeChar = ch
            if ch.isalnum():
                rec_down.Event.KeyEvent.wVirtualKeyCode = ord(ch.upper())
            elif ch == "\r":
                rec_down.Event.KeyEvent.wVirtualKeyCode = 0x0D
                rec_down.Event.KeyEvent.wVirtualScanCode = 0x1C
            elif ch == "\b":
                rec_down.Event.KeyEvent.wVirtualKeyCode = 0x08
                rec_down.Event.KeyEvent.wVirtualScanCode = 0x0E
            records.append(rec_down)

            # Key Up
            rec_up = INPUT_RECORD()
            rec_up.EventType = KEY_EVENT
            rec_up.Event.KeyEvent.bKeyDown = False
            rec_up.Event.KeyEvent.wRepeatCount = 1
            rec_up.Event.KeyEvent.UnicodeChar = ch
            if ch.isalnum():
                rec_up.Event.KeyEvent.wVirtualKeyCode = ord(ch.upper())
            elif ch == "\r":
                rec_up.Event.KeyEvent.wVirtualKeyCode = 0x0D
                rec_up.Event.KeyEvent.wVirtualScanCode = 0x1C
            elif ch == "\b":
                rec_up.Event.KeyEvent.wVirtualKeyCode = 0x08
                rec_up.Event.KeyEvent.wVirtualScanCode = 0x0E
            records.append(rec_up)

        # Write text characters first
        arr_type = INPUT_RECORD * len(records)
        arr = arr_type(*records)
        written = wintypes.DWORD()
        res = kernel32.WriteConsoleInputW(h_conin, arr, len(records), ctypes.byref(written))

        time.sleep(0.05)

        # Send Enter key (VK_RETURN) with hardware scan code 0x1C
        ret_records = []
        for kd in (True, False):
            rec_ret = INPUT_RECORD()
            rec_ret.EventType = KEY_EVENT
            rec_ret.Event.KeyEvent.bKeyDown = kd
            rec_ret.Event.KeyEvent.wRepeatCount = 1
            rec_ret.Event.KeyEvent.UnicodeChar = "\r"
            rec_ret.Event.KeyEvent.wVirtualKeyCode = 0x0D
            rec_ret.Event.KeyEvent.wVirtualScanCode = 0x1C
            ret_records.append(rec_ret)

        ret_arr_type = INPUT_RECORD * len(ret_records)
        ret_arr = ret_arr_type(*ret_records)
        ret_written = wintypes.DWORD()
        ret_res = kernel32.WriteConsoleInputW(h_conin, ret_arr, len(ret_records), ctypes.byref(ret_written))

        kernel32.CloseHandle(h_conin)
        return bool(res and ret_res and (written.value + ret_written.value) > 0)

    finally:
        kernel32.FreeConsole()
