"""Unit tests for HybridStreamSession and TerminalStreamManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from execution.stream_manager import (
    HybridStreamSession,
    TerminalStreamManager,
    collapse_consecutive_lines,
    format_terminal_window,
    strip_ansi,
)


def test_strip_ansi():
    raw = "\x1b[32mHello\x1b[0m \x1b[1mWorld\x1b[0m"
    clean = strip_ansi(raw)
    assert clean == "Hello World"


def test_format_terminal_window():
    short_text = "line 1\nline 2\nline 3"
    formatted = format_terminal_window(short_text, max_chars=100)
    assert formatted == "line 1\nline 2\nline 3"

    # Truncation test
    long_text = "\n".join([f"Output line {i}" for i in range(100)])
    truncated = format_terminal_window(long_text, max_chars=200)
    assert "... [earlier terminal output truncated] ..." in truncated
    assert len(truncated) <= 350


def test_collapse_consecutive_lines():
    lines = [
        "● Read: telegram_bot.py",
        "● Read: telegram_bot.py",
        "● Read: telegram_bot.py",
        "● Edited: telegram_bot.py",
        "● Read: telegram_bot.py",
        "● Read: telegram_bot.py",
    ]
    collapsed = collapse_consecutive_lines(lines)
    assert collapsed == [
        "● Read: telegram_bot.py (x3)",
        "● Edited: telegram_bot.py",
        "● Read: telegram_bot.py (x2)",
    ]


def test_format_terminal_window_strips_html_and_limits_lines():
    raw = "\n".join([
        "o Thought: <i>Thinking about solution</i>",
        "● Ran: <code>git status</code>",
        "● Read: <code>telegram_bot.py</code>",
        "● Read: <code>telegram_bot.py</code>",
        "● Read: <code>telegram_bot.py</code>",
        "● Edited: <code>telegram_bot.py</code>",
        "● Read: <code>test_watcher.py</code>",
        "● Read: <code>test_watcher.py</code>",
        "● Created: <code>test_watcher.py</code>",
        "● Ran: <code>pytest tests/</code>",
    ])
    formatted = format_terminal_window(raw, max_lines=5)
    # Verify no raw HTML tags leaked
    assert "<code>" not in formatted
    assert "</code>" not in formatted
    assert "<i>" not in formatted
    assert "</i>" not in formatted
    # Verify collapsing
    assert "Read: telegram_bot.py (x3)" in formatted
    # Verify windowing
    assert "... [earlier terminal output truncated] ..." in formatted


def test_stream_session_lifecycle():
    async def _run():
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 4242
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        mock_bot.edit_message_text = AsyncMock(return_value=True)

        session = HybridStreamSession(
            bot=mock_bot,
            chat_id=12345,
            title="Test Terminal",
            edit_interval=0.05,
            buffer_debounce=0.01,
        )

        # 1. Start session
        msg_id = await session.start(initial_status="Starting", initial_prompt="echo hello")
        assert msg_id == 4242
        assert session.message_id == 4242
        assert mock_bot.send_message.called
        assert "echo hello" in mock_bot.send_message.call_args.kwargs["text"]

        # 2. Feed output
        session.feed("Starting process...\n")
        session.feed("Step 1 done.\n")
        assert "Step 1 done" in session.get_full_buffer_text()

        # Wait for flush loop to trigger edit
        await asyncio.sleep(0.15)
        assert mock_bot.edit_message_text.called
        last_edit = mock_bot.edit_message_text.call_args.kwargs["text"]
        assert "language-bash" in last_edit
        assert "Step 1 done" in last_edit

        # 3. Complete session with separate notification
        await session.complete(
            final_status="Success",
            event_notification="🎉 <b>Task Completed successfully!</b>",
        )
        assert not session.is_active
        # Check that separate completion notification was sent
        assert mock_bot.send_message.call_count == 2
        comp_msg = mock_bot.send_message.call_args_list[1].kwargs["text"]
        assert "Task Completed successfully!" in comp_msg

    asyncio.run(_run())


def test_stream_session_fail():
    async def _run():
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 5555
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        mock_bot.edit_message_text = AsyncMock(return_value=True)

        session = HybridStreamSession(
            bot=mock_bot,
            chat_id=999,
            title="Fail Test",
            edit_interval=0.05,
            buffer_debounce=0.01,
        )
        await session.start()
        session.feed("Command failed with returncode 1\n")
        await session.fail("Process exited with code 1")

        assert not session.is_active
        # Check separate error event sent
        assert mock_bot.send_message.call_count == 2
        err_msg = mock_bot.send_message.call_args_list[1].kwargs["text"]
        assert "Execution Error Occurred" in err_msg

    asyncio.run(_run())


def test_stream_session_cancel():
    async def _run():
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 7777
        mock_bot.send_message = AsyncMock(return_value=mock_msg)
        mock_bot.edit_message_text = AsyncMock(return_value=True)

        session = HybridStreamSession(
            bot=mock_bot,
            chat_id=999,
            title="Cancel Test",
            edit_interval=0.05,
            buffer_debounce=0.01,
        )
        await session.start()
        await session.cancel()

        assert not session.is_active
        assert mock_bot.send_message.call_count == 2
        cancel_msg = mock_bot.send_message.call_args_list[1].kwargs["text"]
        assert "Task Cancelled" in cancel_msg

    asyncio.run(_run())


def test_manager_session_management():
    async def _run():
        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 1010
        mock_bot.send_message = AsyncMock(return_value=mock_msg)

        mgr = TerminalStreamManager(bot=mock_bot)
        session = await mgr.start_session(chat_id=111, title="Manager Test")
        assert mgr.get_session(111) is session

        mgr.feed(111, "Hello stream\n")
        assert "Hello stream" in session.get_full_buffer_text()

        await mgr.close_session(111)
        assert mgr.get_session(111) is None

    asyncio.run(_run())
