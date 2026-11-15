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
