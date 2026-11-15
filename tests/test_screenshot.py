"""Unit tests for screenshot capture and terminal snapshot rendering."""

from execution.screenshot import get_screenshot, render_terminal_snapshot


def test_render_terminal_snapshot():
    sample_text = (
        "○ Thought: Inspecting project dependencies\n"
        "● Ran: pytest tests/\n"
        "● Edited: execution/telegram_bot.py\n"
        "13 passed in 2.1s\n"
    )
    png_bytes = render_terminal_snapshot(sample_text, title="Test Window")
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    # PNG signature check
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_get_screenshot():
    png_bytes, caption = get_screenshot(fallback_terminal_text="Test prompt execution\n> Finished.")
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Snapshot" in caption
