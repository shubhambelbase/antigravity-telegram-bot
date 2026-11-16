from unittest.mock import MagicMock, patch
import os
import time
import pytest
from execution.telegram_bot import SecretRedactionFilter, check_single_instance


def test_secret_redaction_filter():
    import logging
    f = SecretRedactionFilter()
    token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=f"Connecting with token {token}",
        args=None,
        exc_info=None,
    )
    assert f.filter(record) is True
    assert token not in record.msg
    assert "[REDACTED_TELEGRAM_TOKEN]" in record.msg


def test_secret_redaction_filter_in_args():
    import logging
    f = SecretRedactionFilter()
    token = "987654321:XYZabc1234567890abcdef"
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="Error contacting %s",
        args=(f"https://api.telegram.org/bot{token}/getUpdates",),
        exc_info=None,
    )
    assert f.filter(record) is True
    assert token not in record.args[0]
    assert "[REDACTED_TELEGRAM_TOKEN]" in record.args[0]


def test_check_single_instance_handles_stale_pid(tmp_path):
    test_pid_file = str(tmp_path / ".bot.pid")
    with patch("execution.telegram_bot.PID_FILE", test_pid_file):
        # Write a non-existent PID
        with open(test_pid_file, "w") as f:
            f.write("99999999")

        # check_single_instance should overwrite it with current PID and return True
        res = check_single_instance()
        assert res is True
        with open(test_pid_file, "r") as f:
            assert f.read().strip() == str(os.getpid())


def test_supervisor_loop_exponential_backoff():
    """Verifies that the supervisor loop in main() catches unexpected exceptions,
    retries with backoff, and halts cleanly on KeyboardInterrupt."""
    from execution import telegram_bot

    call_count = 0

    def mock_run_bot():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionResetError("[WinError 10054] Connection reset by peer")
        raise KeyboardInterrupt()

    sleep_calls = []
    with patch.object(telegram_bot, "run_bot", side_effect=mock_run_bot), \
         patch.object(telegram_bot, "check_single_instance", return_value=True), \
         patch.object(telegram_bot, "BOT_TOKEN", "1234:MOCK_TOKEN"), \
         patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):

        telegram_bot.main()

    assert call_count == 3
    # Two failures should trigger backoff sleeps (e.g. 2s, 4s)
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == 2
    assert sleep_calls[1] == 4
