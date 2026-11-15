import pytest
from execution.console_injector import find_interactive_agy_pid, inject_text_to_agy


def test_find_interactive_agy_pid():
    # Should run without error and return None or an integer PID
    pid = find_interactive_agy_pid()
    assert pid is None or isinstance(pid, int)


def test_inject_text_to_invalid_pid():
    # Injecting into an invalid/non-existent PID should safely return False
    res = inject_text_to_agy("test prompt", pid=99999999)
    assert res is False
