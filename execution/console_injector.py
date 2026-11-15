"""Console Keystroke Injector for Windows.

Enables injecting prompt text directly into a running interactive agy.exe
console session via Win32 AttachConsole, VkKeyScanW, MapVirtualKeyW,
and WriteConsoleInputW APIs with precision hardware scan codes and pacing.
"""

import ctypes
from ctypes import wintypes
import logging
import time
from typing import Optional
import psutil

logger = logging.getLogger(__name__)

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# Win32 Constants
KEY_EVENT = 0x0001
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# Setup function prototypes for 64-bit safety
kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.AttachConsole.restype = wintypes.BOOL

kernel32.FreeConsole.argtypes = []
kernel32.FreeConsole.restype = wintypes.BOOL

kernel32.GetConsoleWindow.argtypes = []
kernel32.GetConsoleWindow.restype = wintypes.HWND

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.WriteConsoleInputW.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.WriteConsoleInputW.restype = wintypes.BOOL

user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL


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
    """Finds the PID of the most recently active interactive agy.exe process."""
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "status"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "agy" in name or "antigravity" in name:
                cmdline = proc.info.get("cmdline") or []
                # Exclude headless print mode and help invocations
                if not any(arg in ["-p", "--print", "-h", "--help"] for arg in cmdline):
                    if proc.info.get("status") != psutil.STATUS_ZOMBIE:
                        candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not candidates:
        return None

    # Pick the most recently launched candidate (highest create_time)
    candidates.sort(key=lambda p: p.info.get("create_time", 0.0), reverse=True)
    return candidates[0].info["pid"]


def _build_char_records(ch: str):
    """Builds paired KeyDown and KeyUp INPUT_RECORDs for a character."""
    if ch == "\r":
        vk = 0x0D
        scan = 0x1C
        ctrl_state = 0
    elif ch == "\b":
        vk = 0x08
        scan = 0x0E
        ctrl_state = 0
    elif ch == "\t":
        vk = 0x09
        scan = 0x0F
        ctrl_state = 0
    else:
        scan_res = user32.VkKeyScanW(ch)
        if scan_res != -1:
            vk = scan_res & 0xFF
            shift_state = (scan_res >> 8) & 0xFF
            ctrl_state = 0
            if shift_state & 1:
                ctrl_state |= 0x0010  # SHIFT_PRESSED
            if shift_state & 2:
                ctrl_state |= 0x0008  # LEFT_CTRL_PRESSED
            if shift_state & 4:
                ctrl_state |= 0x0002  # LEFT_ALT_PRESSED
            scan = user32.MapVirtualKeyW(vk, 0)
        else:
            vk = ord(ch.upper()) if ch.isalnum() else 0
            scan = 0
            ctrl_state = 0

    # Key Down
    rec_down = INPUT_RECORD()
    rec_down.EventType = KEY_EVENT
    rec_down.Event.KeyEvent.bKeyDown = True
    rec_down.Event.KeyEvent.wRepeatCount = 1
    rec_down.Event.KeyEvent.UnicodeChar = ch
    rec_down.Event.KeyEvent.wVirtualKeyCode = vk
    rec_down.Event.KeyEvent.wVirtualScanCode = scan
    rec_down.Event.KeyEvent.dwControlKeyState = ctrl_state

    # Key Up
    rec_up = INPUT_RECORD()
    rec_up.EventType = KEY_EVENT
    rec_up.Event.KeyEvent.bKeyDown = False
    rec_up.Event.KeyEvent.wRepeatCount = 1
    rec_up.Event.KeyEvent.UnicodeChar = ch
    rec_up.Event.KeyEvent.wVirtualKeyCode = vk
    rec_up.Event.KeyEvent.wVirtualScanCode = scan
    rec_up.Event.KeyEvent.dwControlKeyState = ctrl_state

    return rec_down, rec_up


def inject_text_to_agy(text: str, pid: Optional[int] = None) -> bool:
    """Injects text + Enter into the interactive agy console window with robust pacing."""
    target_pid = pid or find_interactive_agy_pid()
    if not target_pid:
        logger.warning("No interactive agy process found.")
        return False

    # Normalize prompt: convert any internal newlines to spaces so Bubbletea stays single-line
    clean_text = text.replace("\r\n", " ").replace("\n", " ").strip()
    if not clean_text:
        return False

    kernel32.FreeConsole()
    if not kernel32.AttachConsole(target_pid):
        err = kernel32.GetLastError()
        logger.warning(f"Failed to AttachConsole to PID {target_pid}: error code {err}")
        return False

    try:
        # Focus/wake the console window if available
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

        h_conin = kernel32.CreateFileW(
            "CONIN$",
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h_conin == INVALID_HANDLE_VALUE or not h_conin:
            logger.warning("Failed to open CONIN$ for console writing.")
            return False

        # Paced character injection: write characters in small paced batches
        # to ensure Go Bubbletea's input event slice never drops rapid bursts
        total_chars_written = 0
        written_count = wintypes.DWORD()

        for ch in clean_text:
            rec_down, rec_up = _build_char_records(ch)
            pair_type = INPUT_RECORD * 2
            pair = pair_type(rec_down, rec_up)
            ok = kernel32.WriteConsoleInputW(h_conin, pair, 2, ctypes.byref(written_count))
            if ok:
                total_chars_written += 1
            # Micro-pause between characters (2ms) prevents buffer overflow in Go channel
            time.sleep(0.003)

        if total_chars_written == 0:
            logger.warning("Zero characters were written to CONIN$.")
            kernel32.CloseHandle(h_conin)
            return False

        # Allow Bubbletea textinput component 80ms to finish redrawing before Enter
        time.sleep(0.08)

        # Send Enter KeyDown with hardware scan code 0x1C (VK_RETURN)
        ret_down = INPUT_RECORD()
        ret_down.EventType = KEY_EVENT
        ret_down.Event.KeyEvent.bKeyDown = True
        ret_down.Event.KeyEvent.wRepeatCount = 1
        ret_down.Event.KeyEvent.UnicodeChar = "\r"
        ret_down.Event.KeyEvent.wVirtualKeyCode = 0x0D
        ret_down.Event.KeyEvent.wVirtualScanCode = 0x1C
        ret_down.Event.KeyEvent.dwControlKeyState = 0

        single_type = INPUT_RECORD * 1
        arr_ret_down = single_type(ret_down)
        kernel32.WriteConsoleInputW(h_conin, arr_ret_down, 1, ctypes.byref(written_count))

        # Hold Enter down for 30ms to guarantee event registration
        time.sleep(0.03)

        # Send Enter KeyUp
        ret_up = INPUT_RECORD()
        ret_up.EventType = KEY_EVENT
        ret_up.Event.KeyEvent.bKeyDown = False
        ret_up.Event.KeyEvent.wRepeatCount = 1
        ret_up.Event.KeyEvent.UnicodeChar = "\r"
        ret_up.Event.KeyEvent.wVirtualKeyCode = 0x0D
        ret_up.Event.KeyEvent.wVirtualScanCode = 0x1C
        ret_up.Event.KeyEvent.dwControlKeyState = 0

        arr_ret_up = single_type(ret_up)
        kernel32.WriteConsoleInputW(h_conin, arr_ret_up, 1, ctypes.byref(written_count))

        time.sleep(0.04)
        kernel32.CloseHandle(h_conin)
        logger.info(f"Successfully injected {total_chars_written} chars + Enter into PID {target_pid}")
        return True

    except Exception as e:
        logger.error(f"Exception during console injection: {e}", exc_info=True)
        return False

    finally:
        kernel32.FreeConsole()


def inject_special_key(key_name: str, pid: Optional[int] = None) -> bool:
    """Injects interactive navigation/prompt keys like 'yes', 'no', 'enter', 'up', 'down', 'space', '1', '2', 'ctrl_c'."""
    target_pid = pid or find_interactive_agy_pid()
    if not target_pid:
        logger.warning("No interactive agy process found.")
        return False

    name = key_name.strip().lower()

    if name in ("yes", "y"):
        return inject_text_to_agy("y", pid=target_pid)
    elif name in ("no", "n"):
        return inject_text_to_agy("n", pid=target_pid)
    elif name in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        return inject_text_to_agy(name, pid=target_pid)

    # Low-level virtual key codes for navigation & control
    VK_MAP = {
        "enter": (0x0D, 0x1C, "\r", 0),
        "return": (0x0D, 0x1C, "\r", 0),
        "up": (0x26, 0x48, "\x00", 0x0100),       # ENHANCED_KEY
        "down": (0x28, 0x50, "\x00", 0x0100),     # ENHANCED_KEY
        "left": (0x25, 0x4B, "\x00", 0x0100),     # ENHANCED_KEY
        "right": (0x27, 0x4D, "\x00", 0x0100),    # ENHANCED_KEY
        "space": (0x20, 0x39, " ", 0),
        "backspace": (0x08, 0x0E, "\b", 0),
        "tab": (0x09, 0x0F, "\t", 0),
        "escape": (0x1B, 0x01, "\x1B", 0),
        "ctrl_c": (0x43, 0x2E, "\x03", 0x0008),   # LEFT_CTRL_PRESSED
    }

    if name not in VK_MAP:
        logger.warning(f"Unsupported special key: {name}")
        return False

    vk, scan, uchar, ctrl_state = VK_MAP[name]

    kernel32.FreeConsole()
    if not kernel32.AttachConsole(target_pid):
        logger.warning(f"Failed to AttachConsole to PID {target_pid}")
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
        if h_conin == INVALID_HANDLE_VALUE or not h_conin:
            return False

        written = wintypes.DWORD()
        single_type = INPUT_RECORD * 1

        # KeyDown
        rec_down = INPUT_RECORD()
        rec_down.EventType = KEY_EVENT
        rec_down.Event.KeyEvent.bKeyDown = True
        rec_down.Event.KeyEvent.wRepeatCount = 1
        rec_down.Event.KeyEvent.UnicodeChar = uchar
        rec_down.Event.KeyEvent.wVirtualKeyCode = vk
        rec_down.Event.KeyEvent.wVirtualScanCode = scan
        rec_down.Event.KeyEvent.dwControlKeyState = ctrl_state
        arr_down = single_type(rec_down)
        kernel32.WriteConsoleInputW(h_conin, arr_down, 1, ctypes.byref(written))

        time.sleep(0.03)

        # KeyUp
        rec_up = INPUT_RECORD()
        rec_up.EventType = KEY_EVENT
        rec_up.Event.KeyEvent.bKeyDown = False
        rec_up.Event.KeyEvent.wRepeatCount = 1
        rec_up.Event.KeyEvent.UnicodeChar = uchar
        rec_up.Event.KeyEvent.wVirtualKeyCode = vk
        rec_up.Event.KeyEvent.wVirtualScanCode = scan
        rec_up.Event.KeyEvent.dwControlKeyState = ctrl_state
        arr_up = single_type(rec_up)
        kernel32.WriteConsoleInputW(h_conin, arr_up, 1, ctypes.byref(written))

        time.sleep(0.02)
        kernel32.CloseHandle(h_conin)
        logger.info(f"Injected special key '{name}' to PID {target_pid}")
        return True

    except Exception as e:
        logger.error(f"Error injecting special key: {e}")
        return False
    finally:
        kernel32.FreeConsole()

