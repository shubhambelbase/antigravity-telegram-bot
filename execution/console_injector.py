"""Console Keystroke Injector for Windows.

Enables injecting prompt text directly into a running interactive agy.exe
console session via Win32 AttachConsole, VkKeyScanW, MapVirtualKeyW,
and WriteConsoleInputW APIs with precision hardware scan codes and pacing.

Uses a short-lived isolated worker subprocess for Win32 console attachment
so the parent bot daemon never detaches its own console via FreeConsole()
and cannot be killed by GenerateConsoleCtrlEvent.
"""

import ctypes
from ctypes import wintypes
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import psutil

logger = logging.getLogger(__name__)

_console_lock = threading.Lock()
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if os.name == "nt":
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
    CREATE_NO_WINDOW = 0x08000000

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

    kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL

    user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user32.VkKeyScanW.restype = ctypes.c_short

    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
else:
    kernel32 = None
    user32 = None
    KEY_EVENT = 0x0001
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = -1
    CREATE_NO_WINDOW = 0


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


PRESENCE_LOCK_RE = re.compile(r"presence[\\/]([a-f0-9\-]{36})\.lock", re.IGNORECASE)
CONV_DB_RE = re.compile(r"(?:conversations|presence)[\\/]([a-f0-9\-]{36})\.(?:db|lock)", re.IGNORECASE)


def get_agy_process_conv_id(proc: psutil.Process) -> Optional[str]:
    """Inspects a process open files (and memory maps fallback) to identify its active conversation UUID."""
    try:
        open_paths = [f.path for f in proc.open_files()]
        # Prefer presence/*.lock as the primary indicator of the currently attached interactive session
        for path in open_paths:
            match = PRESENCE_LOCK_RE.search(path)
            if match:
                return match.group(1)
        for path in open_paths:
            match = CONV_DB_RE.search(path)
            if match:
                return match.group(1)
    except Exception:
        pass

    try:
        for m in proc.memory_maps():
            match = CONV_DB_RE.search(m.path)
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


def _paths_match(p1: str, p2: str) -> bool:
    if not p1 or not p2:
        return False
    try:
        return os.path.samefile(p1, p2)
    except Exception:
        return os.path.normcase(os.path.abspath(p1)) == os.path.normcase(os.path.abspath(p2))


def list_interactive_agy_processes() -> List[Dict[str, Any]]:
    """Lists all running interactive agy processes with their PID, conversation ID, and workspace."""
    results = []
    VALID_AGY_BINARIES = {"agy.exe", "agy", "antigravity.exe", "antigravity"}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in VALID_AGY_BINARIES:
                continue

            cmdline = proc.cmdline() or []
            # Exclude headless print mode, acp stdio server, remote-control daemon, and help invocations
            if any(arg in ["-p", "--print", "--prompt", "-h", "--help", "acp", "remote-control"] for arg in cmdline):
                continue
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue

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
                "create_time": proc.create_time(),
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
       - Matches process whose open files/maps match conv_id.
       - If no direct match, matches an interactive process in conv_id's workspace ONLY if that
         process does not already hold a different conversation ID.
       - Returns None if no matching interactive terminal is open (prevents cross-session hijacking).
    2. If workspace is provided (without conv_id):
       - Matches process whose cwd matches workspace; returns None if none match (never hijacks
         another workspace's terminal).
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
        for cand in candidates:
            c_id = cand.get("conv_id")
            if c_id and (c_id == clean_conv or c_id.startswith(clean_conv)):
                return cand["pid"]

        # Fallback to workspace ONLY if candidate has no conflicting conversation ID
        conv_ws = get_workspace_for_conversation(clean_conv)
        if conv_ws:
            for cand in candidates:
                c_id = cand.get("conv_id")
                if c_id and c_id != clean_conv and not c_id.startswith(clean_conv):
                    continue
                if _paths_match(cand.get("cwd", ""), conv_ws):
                    return cand["pid"]

        return None

    # Step 2: Strict workspace match when workspace is specified
    if workspace:
        clean_ws = os.path.abspath(workspace)
        for cand in candidates:
            if _paths_match(cand.get("cwd", ""), clean_ws):
                return cand["pid"]
        return None

    # Step 3: Default to most recently launched candidate when unfiltered
    return candidates[0]["pid"]


def _get_input_records_for_char(ch: str):
    """Builds paired KeyDown and KeyUp INPUT_RECORDs for a character.
    Handles UTF-16 surrogate pairs for characters outside BMP (> 0xFFFF), e.g. emojis.
    Returns a list of (rec_down, rec_up) tuples.
    """
    if ord(ch) > 0xFFFF:
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
            scan_res = user32.VkKeyScanW(ch) if user32 else -1
        except Exception:
            scan_res = -1

        if scan_res != -1 and user32:
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

    rec_down = INPUT_RECORD()
    rec_down.EventType = KEY_EVENT
    rec_down.Event.KeyEvent.bKeyDown = True
    rec_down.Event.KeyEvent.wRepeatCount = 1
    rec_down.Event.KeyEvent.UnicodeChar = ch
    rec_down.Event.KeyEvent.wVirtualKeyCode = vk
    rec_down.Event.KeyEvent.wVirtualScanCode = scan
    rec_down.Event.KeyEvent.dwControlKeyState = ctrl_state

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


def _in_process_inject_text(clean_text: str, target_pid: int, submit: bool = True) -> tuple[bool, Optional[str], int]:
    """Executes raw Win32 AttachConsole + WriteConsoleInputW for text. Intended to run in worker subprocess."""
    if not kernel32 or not user32:
        return False, "Console injection is only supported on Windows.", 0

    input_records = []
    try:
        for ch in clean_text:
            for rec_down, rec_up in _get_input_records_for_char(ch):
                input_records.append((rec_down, rec_up))
    except Exception as e:
        return False, f"Failed to prepare input records for prompt: {e}", 0

    success = False
    err_message = None
    total_chars_written = 0

    with _console_lock:
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(target_pid):
            err = kernel32.GetLastError()
            return False, f"Failed to AttachConsole to PID {target_pid}: error code {err}", 0

        h_conin = None
        try:
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                try:
                    user32.AllowSetForegroundWindow(target_pid)
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
                    if ok and written_count.value == 2:
                        total_chars_written += 1
                    else:
                        err_message = f"WriteConsoleInputW wrote {written_count.value}/2 records."
                        break
                    time.sleep(0.003)

                if total_chars_written == len(input_records) and total_chars_written > 0:
                    if submit:
                        pre_enter_delay = max(0.12, min(1.0, len(clean_text) * 0.001))
                        time.sleep(pre_enter_delay)

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
                        ok_d = kernel32.WriteConsoleInputW(h_conin, arr_ret_down, 1, ctypes.byref(written_count))
                        time.sleep(0.04)

                        ret_up = INPUT_RECORD()
                        ret_up.EventType = KEY_EVENT
                        ret_up.Event.KeyEvent.bKeyDown = False
                        ret_up.Event.KeyEvent.wRepeatCount = 1
                        ret_up.Event.KeyEvent.UnicodeChar = "\r"
                        ret_up.Event.KeyEvent.wVirtualKeyCode = 0x0D
                        ret_up.Event.KeyEvent.wVirtualScanCode = 0x1C
                        ret_up.Event.KeyEvent.dwControlKeyState = 0

                        arr_ret_up = single_type(ret_up)
                        ok_u = kernel32.WriteConsoleInputW(h_conin, arr_ret_up, 1, ctypes.byref(written_count))
                        time.sleep(0.04)
                        success = bool(ok_d and ok_u)
                        if not success:
                            err_message = "Failed writing Enter key event to CONIN$."
                    else:
                        success = True
                elif not err_message:
                    err_message = "Zero characters were written to CONIN$."
        except Exception as e:
            err_message = f"Exception during console injection: {e}"
        finally:
            if h_conin and h_conin != INVALID_HANDLE_VALUE:
                try:
                    kernel32.CloseHandle(h_conin)
                except Exception:
                    pass
            kernel32.FreeConsole()

    return success, err_message, total_chars_written


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


def _in_process_inject_special_key(name: str, target_pid: int) -> tuple[bool, Optional[str]]:
    """Executes Win32 AttachConsole + special key injection. Intended to run in worker subprocess."""
    if not kernel32:
        return False, "Console injection is only supported on Windows."

    if name in ("yes", "y"):
        ok, err, _ = _in_process_inject_text("y", target_pid, submit=True)
        return ok, err
    if name in ("no", "n"):
        ok, err, _ = _in_process_inject_text("n", target_pid, submit=True)
        return ok, err
    if name in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        # Menu selection numbers in TUIs often act immediately without needing a trailing Enter
        ok, err, _ = _in_process_inject_text(name, target_pid, submit=False)
        return ok, err

    if name not in VK_MAP:
        return False, f"Unsupported special key: {name}"

    vk, scan, uchar, ctrl_state = VK_MAP[name]
    success = False
    err_message = None

    with _console_lock:
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(target_pid):
            err = kernel32.GetLastError()
            return False, f"Failed to AttachConsole to PID {target_pid}: error code {err}"

        h_conin = None
        ctrl_ignored = False
        try:
            if name == "ctrl_c":
                # Shield this worker process from CTRL_C_EVENT before signalling the target console
                ctrl_ignored = bool(kernel32.SetConsoleCtrlHandler(None, True))

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

                rec_down = INPUT_RECORD()
                rec_down.EventType = KEY_EVENT
                rec_down.Event.KeyEvent.bKeyDown = True
                rec_down.Event.KeyEvent.wRepeatCount = 1
                rec_down.Event.KeyEvent.UnicodeChar = uchar
                rec_down.Event.KeyEvent.wVirtualKeyCode = vk
                rec_down.Event.KeyEvent.wVirtualScanCode = scan
                rec_down.Event.KeyEvent.dwControlKeyState = ctrl_state
                arr_down = single_type(rec_down)
                ok_d = kernel32.WriteConsoleInputW(h_conin, arr_down, 1, ctypes.byref(written))

                time.sleep(0.02)

                rec_up = INPUT_RECORD()
                rec_up.EventType = KEY_EVENT
                rec_up.Event.KeyEvent.bKeyDown = False
                rec_up.Event.KeyEvent.wRepeatCount = 1
                rec_up.Event.KeyEvent.UnicodeChar = uchar
                rec_up.Event.KeyEvent.wVirtualKeyCode = vk
                rec_up.Event.KeyEvent.wVirtualScanCode = scan
                rec_up.Event.KeyEvent.dwControlKeyState = ctrl_state
                arr_up = single_type(rec_up)
                ok_u = kernel32.WriteConsoleInputW(h_conin, arr_up, 1, ctypes.byref(written))

                time.sleep(0.02)
                success = bool(ok_d and ok_u)

                if name == "ctrl_c":
                    try:
                        sent = bool(kernel32.GenerateConsoleCtrlEvent(0, target_pid))
                        if not sent:
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
            kernel32.FreeConsole()
            if ctrl_ignored:
                try:
                    kernel32.SetConsoleCtrlHandler(None, False)
                except Exception:
                    pass

    return success, err_message


def _run_injection_worker(payload: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    """Runs console injection in an isolated short-lived subprocess so the bot keeps its own console."""
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_PROJECT_ROOT}{os.pathsep}{existing_pp}" if existing_pp else _PROJECT_ROOT

    creationflags = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "execution.console_injector", "--worker"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_PROJECT_ROOT,
            env=env,
            creationflags=creationflags,
        )
        out = (proc.stdout or "").strip()
        if out:
            last_line = out.splitlines()[-1]
            return json.loads(last_line)
        return {"ok": False, "error": proc.stderr.strip() or f"Worker exited with {proc.returncode}", "chars": 0}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Console injection worker timed out.", "chars": 0}
    except Exception as e:
        return {"ok": False, "error": f"Failed to run console worker: {e}", "chars": 0}


def inject_text_to_agy(
    text: str,
    pid: Optional[int] = None,
    conv_id: Optional[str] = None,
    workspace: Optional[str] = None,
    submit: bool = True,
) -> bool:
    """Injects text (+ Enter if submit=True) into the interactive agy console window safely."""
    target_pid = pid or find_interactive_agy_pid(conv_id=conv_id, workspace=workspace)
    if not target_pid:
        logger.warning("No interactive agy process found.")
        return False

    clean_text = text.replace("\r\n", " ").replace("\n", " ").strip()
    if not clean_text:
        return False

    if not psutil.pid_exists(target_pid):
        logger.warning(f"Failed to AttachConsole to PID {target_pid}: error code 87")
        return False

    timeout = max(15.0, len(clean_text) * 0.01 + 10.0)
    res = _run_injection_worker(
        {"mode": "text", "pid": target_pid, "text": clean_text, "submit": submit},
        timeout=timeout,
    )
    if res.get("ok"):
        chars = res.get("chars", len(clean_text))
        suffix = " + Enter" if submit else ""
        logger.info(f"Successfully injected {chars} chars{suffix} into PID {target_pid}")
        return True

    if res.get("error"):
        logger.warning(res["error"])
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
    valid_names = set(VK_MAP.keys()) | {"yes", "y", "no", "n", "1", "2", "3", "4", "5", "6", "7", "8", "9"}
    if name not in valid_names:
        logger.warning(f"Unsupported special key: {name}")
        return False

    if not psutil.pid_exists(target_pid):
        logger.warning(f"Failed to AttachConsole to PID {target_pid}: error code 87")
        return False

    res = _run_injection_worker({"mode": "key", "pid": target_pid, "key": name}, timeout=10.0)
    if res.get("ok"):
        logger.info(f"Injected special key '{name}' to PID {target_pid}")
        return True

    if res.get("error"):
        logger.warning(res["error"])
    return False


def is_agy_process_busy(pid: Optional[int] = None) -> bool:
    """Checks if an agy process or its child processes are actively executing non-MCP tools."""
    target_pid = pid or find_interactive_agy_pid()
    if not target_pid:
        return False
    try:
        proc = psutil.Process(target_pid)
        for child in proc.children(recursive=True):
            if not child.is_running():
                continue
            cname = child.name().lower()
            try:
                cmd = " ".join(child.cmdline() or []).lower()
            except Exception:
                cmd = ""
            # Ignore persistent MCP server sidecars launched by agy
            if "mcp_server" in cmd or "mcp" in cmd and ("python" in cname or "uv" in cname):
                continue
            if any(tool in cname for tool in ("python", "git", "cargo", "npm", "node", "pytest", "bash", "powershell", "cmd", "gradle", "mvn")):
                return True
    except Exception:
        pass
    return False


def _worker_main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"Invalid worker payload: {e}", "chars": 0}))
        return 1

    mode = payload.get("mode")
    pid = int(payload.get("pid") or 0)
    if mode == "text":
        ok, err, chars = _in_process_inject_text(
            str(payload.get("text", "")),
            pid,
            submit=bool(payload.get("submit", True)),
        )
        print(json.dumps({"ok": ok, "error": err, "chars": chars}))
        return 0 if ok else 1
    if mode == "key":
        ok, err = _in_process_inject_special_key(str(payload.get("key", "")), pid)
        print(json.dumps({"ok": ok, "error": err, "chars": 0}))
        return 0 if ok else 1

    print(json.dumps({"ok": False, "error": f"Unknown mode: {mode}", "chars": 0}))
    return 1


if __name__ == "__main__" and "--worker" in sys.argv:
    sys.exit(_worker_main())
