"""Console Keystroke Injector for Windows.

Enables injecting prompt text directly into a running interactive agy.exe
console session via Win32 AttachConsole, VkKeyScanW, MapVirtualKeyW,
and WriteConsoleInputW APIs with precision hardware scan codes and pacing.
"""

import ctypes
from ctypes import wintypes
import json
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import psutil

logger = logging.getLogger(__name__)

_console_lock = threading.Lock()

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

kernel32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL

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


CONV_DB_RE = re.compile(r"conversations[\\/]([a-f0-9\-]{36})\.db", re.IGNORECASE)


def get_agy_process_conv_id(proc: psutil.Process) -> Optional[str]:
    """Inspects a process memory maps and open files to identify its active conversation UUID."""
    try:
        for m in proc.memory_maps():
            match = CONV_DB_RE.search(m.path)
            if match:
                return match.group(1)
    except Exception:
        pass
    try:
        for f in proc.open_files():
            match = CONV_DB_RE.search(f.path)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def get_workspace_for_conversation(conv_id: str) -> Optional[str]:
    """Looks up the workspace directory associated with a conversation UUID from history.jsonl."""
    history_path = os.path.expanduser("~/.gemini/antigravity-cli/history.jsonl")
    if not os.path.isfile(history_path):
        return None
    try:
        with open(history_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("conversationId") == conv_id:
                    ws = entry.get("workspace")
                    if ws and os.path.isdir(ws):
                        return ws
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Error reading history.jsonl: {e}")
    return None


def list_interactive_agy_processes() -> List[Dict[str, Any]]:
    """Lists all running interactive agy processes with their PID, conversation ID, and workspace."""
    results = []
    VALID_AGY_BINARIES = {"agy.exe", "agy", "antigravity.exe", "antigravity"}
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "status"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []

            is_agy = name in VALID_AGY_BINARIES
            if not is_agy and cmdline:
                first_arg = os.path.basename(cmdline[0]).lower()
                is_agy = first_arg in VALID_AGY_BINARIES

            if is_agy:
                # Exclude headless print mode and help invocations
                if not any(arg in ["-p", "--print", "-h", "--help"] for arg in cmdline):
                    if proc.info.get("status") != psutil.STATUS_ZOMBIE:
                        try:
                            cwd = proc.cwd()
                        except Exception:
                            cwd = ""
                        conv_id = get_agy_process_conv_id(proc)
                        results.append({
                            "pid": proc.info["pid"],
                            "proc": proc,
                            "cwd": cwd,
                            "conv_id": conv_id,
                            "create_time": proc.info.get("create_time", 0.0),
                        })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    results.sort(key=lambda x: x["create_time"], reverse=True)
    return results


def find_interactive_agy_pid(
    conv_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Optional[int]:
    """Finds the PID of the interactive agy.exe process matching the requested session or workspace.

    1. If conv_id is provided:
       - Matches process whose open memory map contains conversations/<conv_id>.db.
       - If no direct memory map match, matches process whose cwd matches the workspace of conv_id.
       - Returns None if conv_id was explicitly requested but no matching interactive terminal is open.
    2. If workspace is provided:
       - Matches process whose cwd matches workspace.
    3. If neither is provided:
       - Returns the most recently launched candidate.
    """
    raw_candidates = list_interactive_agy_processes()
    if not raw_candidates:
        return None
    candidates = sorted(raw_candidates, key=lambda x: x.get("create_time", 0.0), reverse=True)

    # Step 1: Match by conversation ID if requested
    if conv_id:
        clean_conv = conv_id.strip()
        # Direct session database match
        for cand in candidates:
            if cand["conv_id"] and (cand["conv_id"] == clean_conv or cand["conv_id"].startswith(clean_conv)):
                return cand["pid"]

        # Fallback to workspace of this conversation
        conv_ws = get_workspace_for_conversation(clean_conv)
        if conv_ws:
            for cand in candidates:
                cand_cwd = cand["cwd"]
                if cand_cwd:
                    try:
                        if os.path.samefile(cand_cwd, conv_ws):
                            return cand["pid"]
                    except Exception:
                        if cand_cwd.lower() == conv_ws.lower():
                            return cand["pid"]

        # An explicit conversation was requested, but it is NOT running in any interactive desktop window!
        # Return None to prevent hijacking an unrelated desktop window.
        return None

    # Step 2: Match by workspace if provided
    if workspace:
        clean_ws = os.path.abspath(workspace)
        for cand in candidates:
            cand_cwd = cand["cwd"]
            if cand_cwd:
                try:
                    if os.path.samefile(cand_cwd, clean_ws):
                        return cand["pid"]
                except Exception:
                    if cand_cwd.lower() == clean_ws.lower():
                        return cand["pid"]

    # Step 3: Default to most recently launched candidate
    return candidates[0]["pid"]


def _get_input_records_for_char(ch: str):
    """Builds paired KeyDown and KeyUp INPUT_RECORDs for a character.
    Handles UTF-16 surrogate pairs for characters outside BMP (> 0xFFFF), e.g. emojis.
    Returns a list of (rec_down, rec_up) tuples.
    """
    if ord(ch) > 0xFFFF:
        # Non-BMP character (e.g. emoji like '\U0001f517' or link symbols)
        utf16_bytes = ch.encode("utf-16-le")
        wchar_chars = [
            chr(int.from_bytes(utf16_bytes[0:2], "little")),
            chr(int.from_bytes(utf16_bytes[2:4], "little")),
        ]
        results = []
        for wch in wchar_chars:
            rec_down = INPUT_RECORD()
            rec_down.EventType = KEY_EVENT
            rec_down.Event.KeyEvent.bKeyDown = True
            rec_down.Event.KeyEvent.wRepeatCount = 1
            rec_down.Event.KeyEvent.UnicodeChar = wch
            rec_down.Event.KeyEvent.wVirtualKeyCode = 0
            rec_down.Event.KeyEvent.wVirtualScanCode = 0
            rec_down.Event.KeyEvent.dwControlKeyState = 0

            rec_up = INPUT_RECORD()
            rec_up.EventType = KEY_EVENT
            rec_up.Event.KeyEvent.bKeyDown = False
            rec_up.Event.KeyEvent.wRepeatCount = 1
            rec_up.Event.KeyEvent.UnicodeChar = wch
            rec_up.Event.KeyEvent.wVirtualKeyCode = 0
            rec_up.Event.KeyEvent.wVirtualScanCode = 0
            rec_up.Event.KeyEvent.dwControlKeyState = 0
            results.append((rec_down, rec_up))
        return results

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
        try:
            scan_res = user32.VkKeyScanW(ch)
        except Exception:
            scan_res = -1

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

    return [(rec_down, rec_up)]


def _build_char_records(ch: str):
    """Backward-compatible helper returning the primary (rec_down, rec_up) pair for a character."""
    pairs = _get_input_records_for_char(ch)
    return pairs[0]


def inject_text_to_agy(
    text: str,
    pid: Optional[int] = None,
    conv_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> bool:
    """Injects text + Enter into the interactive agy console window with robust pacing.
    Guarantees that console is detached BEFORE any logging so bot logs never leak into target terminal.
    """
    target_pid = pid or find_interactive_agy_pid(conv_id=conv_id, workspace=workspace)
    if not target_pid:
        logger.warning("No interactive agy process found.")
        return False

    # Normalize prompt: convert any internal newlines to spaces so Bubbletea stays single-line
    clean_text = text.replace("\r\n", " ").replace("\n", " ").strip()
    if not clean_text:
        return False

    # Pre-build all input records in memory before attaching to console
    input_records = []
    try:
        for ch in clean_text:
            for rec_down, rec_up in _get_input_records_for_char(ch):
                input_records.append((rec_down, rec_up))
    except Exception as e:
        logger.error(f"Failed to prepare input records for prompt: {e}")
        return False

    success = False
    err_message = None
    total_chars_written = 0

    with _console_lock:
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(target_pid):
            err = kernel32.GetLastError()
            logger.warning(f"Failed to AttachConsole to PID {target_pid}: error code {err}")
            return False

        h_conin = None
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
                err_message = "Failed to open CONIN$ for console writing."
            else:
                written_count = wintypes.DWORD()
                pair_type = INPUT_RECORD * 2

                for rec_down, rec_up in input_records:
                    pair = pair_type(rec_down, rec_up)
                    ok = kernel32.WriteConsoleInputW(h_conin, pair, 2, ctypes.byref(written_count))
                    if ok:
                        total_chars_written += 1
                    time.sleep(0.003)

                if total_chars_written > 0:
                    # Allow Bubbletea textinput component to finish redrawing before Enter
                    time.sleep(0.06)

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

                    time.sleep(0.02)

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
                    time.sleep(0.02)
                    success = True
                else:
                    err_message = "Zero characters were written to CONIN$."
        except Exception as e:
            err_message = f"Exception during console injection: {e}"
        finally:
            if h_conin and h_conin != INVALID_HANDLE_VALUE:
                try:
                    kernel32.CloseHandle(h_conin)
                except Exception:
                    pass
            # CRITICAL: Detach console BEFORE any logging to prevent log leak into target terminal
            kernel32.FreeConsole()

    # Log results safely outside of the attached console
    if success:
        logger.info(f"Successfully injected {total_chars_written} chars + Enter into PID {target_pid}")
        return True
    else:
        if err_message:
            logger.warning(err_message)
        return False


def inject_special_key(
    key_name: str,
    pid: Optional[int] = None,
    conv_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> bool:
    """Injects interactive navigation/prompt keys like 'yes', 'no', 'enter', 'up', 'down', 'space', '1', '2', 'ctrl_c'."""
    target_pid = pid or find_interactive_agy_pid(conv_id=conv_id, workspace=workspace)
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
    success = False
    err_message = None

    with _console_lock:
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(target_pid):
            logger.warning(f"Failed to AttachConsole to PID {target_pid}")
            return False

        h_conin = None
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
            if h_conin != INVALID_HANDLE_VALUE and h_conin:
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

                time.sleep(0.02)

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
                success = True

                if name == "ctrl_c":
                    try:
                        # Send CTRL_C_EVENT (0) to process group
                        kernel32.GenerateConsoleCtrlEvent(0, 0)
                    except Exception:
                        pass
            else:
                err_message = "Failed to open CONIN$ for special key writing."
        except Exception as e:
            err_message = f"Error injecting special key: {e}"
        finally:
            if h_conin and h_conin != INVALID_HANDLE_VALUE:
                try:
                    kernel32.CloseHandle(h_conin)
                except Exception:
                    pass
            # Detach console BEFORE any logging
            kernel32.FreeConsole()

    if success:
        logger.info(f"Injected special key '{name}' to PID {target_pid}")
        return True
    else:
        if err_message:
            logger.warning(err_message)
        return False

