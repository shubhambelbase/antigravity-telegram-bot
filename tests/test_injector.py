import pytest
from execution.console_injector import (
    _build_char_records,
    find_interactive_agy_pid,
    inject_special_key,
    inject_text_to_agy,
)


def test_find_interactive_agy_pid():
    pid = find_interactive_agy_pid()
    assert pid is None or isinstance(pid, int)


def test_find_interactive_agy_pid_with_mocked_processes(monkeypatch):
    from execution.console_injector import list_interactive_agy_processes

    mock_procs = [
        {"pid": 1111, "cwd": "E:\\project_a", "conv_id": "aaaa-1111-2222-3333", "create_time": 100.0},
        {"pid": 2222, "cwd": "C:\\project_b", "conv_id": "bbbb-4444-5555-6666", "create_time": 200.0},
    ]

    monkeypatch.setattr("execution.console_injector.list_interactive_agy_processes", lambda: mock_procs)

    # 1. Match by conversation ID
    assert find_interactive_agy_pid(conv_id="aaaa-1111-2222-3333") == 1111
    assert find_interactive_agy_pid(conv_id="bbbb-4444-5555-6666") == 2222

    # 2. Unknown conversation ID -> Returns None (prevents hijacking unrelated terminal)
    assert find_interactive_agy_pid(conv_id="unknown-9999-0000") is None

    # 3. Match by workspace
    assert find_interactive_agy_pid(workspace="E:\\project_a") == 1111
    assert find_interactive_agy_pid(workspace="C:\\project_b") == 2222

    # 4. No filter -> Returns newest candidate (2222)
    assert find_interactive_agy_pid() == 2222


def test_inject_text_to_invalid_pid():
    res = inject_text_to_agy("test prompt", pid=99999999)
    assert res is False


def test_inject_special_key_invalid():
    res = inject_special_key("unsupported_xyz", pid=99999999)
    assert res is False

    res_valid_key = inject_special_key("yes", pid=99999999)
    assert res_valid_key is False


def test_build_char_records_alphanumeric():
    rec_down, rec_up = _build_char_records("a")
    assert rec_down.EventType == 1
    assert bool(rec_down.Event.KeyEvent.bKeyDown) is True
    assert bool(rec_up.Event.KeyEvent.bKeyDown) is False
    assert rec_down.Event.KeyEvent.UnicodeChar == "a"
    assert rec_down.Event.KeyEvent.wVirtualKeyCode == 0x41


def test_build_char_records_space_and_punctuation():
    rec_down, rec_up = _build_char_records(" ")
    assert rec_down.Event.KeyEvent.UnicodeChar == " "
    assert rec_down.Event.KeyEvent.wVirtualKeyCode == 0x20
    assert rec_down.Event.KeyEvent.wVirtualScanCode == 0x39

    rec_colon_down, _ = _build_char_records(":")
    assert rec_colon_down.Event.KeyEvent.UnicodeChar == ":"
    assert rec_colon_down.Event.KeyEvent.wVirtualKeyCode > 0
    # Colon requires shift key
    assert rec_colon_down.Event.KeyEvent.dwControlKeyState & 0x0010


def test_build_char_records_special_keys():
    rec_ret, _ = _build_char_records("\r")
    assert rec_ret.Event.KeyEvent.wVirtualKeyCode == 0x0D
    assert rec_ret.Event.KeyEvent.wVirtualScanCode == 0x1C

    rec_back, _ = _build_char_records("\b")
    assert rec_back.Event.KeyEvent.wVirtualKeyCode == 0x08
    assert rec_back.Event.KeyEvent.wVirtualScanCode == 0x0E


def test_build_char_records_emoji_and_non_bmp():
    # Test non-BMP character like '\U0001f517' (link symbol)
    from execution.console_injector import _get_input_records_for_char
    pairs = _get_input_records_for_char("\U0001f517")
    assert len(pairs) == 2  # High and low surrogate pair
    
    # First surrogate
    down1, up1 = pairs[0]
    assert bool(down1.Event.KeyEvent.bKeyDown) is True
    assert bool(up1.Event.KeyEvent.bKeyDown) is False
    assert ord(down1.Event.KeyEvent.UnicodeChar) == 0xD83D
    
    # Second surrogate
    down2, up2 = pairs[1]
    assert ord(down2.Event.KeyEvent.UnicodeChar) == 0xDD17

    # Backward compatibility with _build_char_records
    rec_down, rec_up = _build_char_records("\U0001f517")
    assert ord(rec_down.Event.KeyEvent.UnicodeChar) == 0xD83D
