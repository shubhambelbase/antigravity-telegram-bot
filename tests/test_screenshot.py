"""Unit tests for screenshot capture and terminal snapshot rendering."""

import io
from PIL import Image, ImageDraw
from unittest.mock import patch

from execution.screenshot import (
    ensure_desktop_access,
    is_blank_or_invalid_image,
    capture_desktop_screenshot,
    get_screenshot,
    optimize_and_compress_image,
    render_terminal_snapshot,
)


def test_is_blank_or_invalid_image():
    # None or tiny
    assert is_blank_or_invalid_image(None) is True
    assert is_blank_or_invalid_image(Image.new("RGB", (1, 1))) is True

    # 100% Transparent
    transparent = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    assert is_blank_or_invalid_image(transparent) is True

    # Solid single colors
    solid_white = Image.new("RGB", (100, 100), (255, 255, 255))
    assert is_blank_or_invalid_image(solid_white) is True

    solid_black = Image.new("RGB", (100, 100), (0, 0, 0))
    assert is_blank_or_invalid_image(solid_black) is True

    # Real image with varying colors
    multi_color = Image.new("RGB", (100, 100), (50, 50, 50))
    draw = ImageDraw.Draw(multi_color)
    draw.rectangle([10, 10, 40, 40], fill=(200, 100, 50))
    draw.text((15, 15), "Antigravity", fill=(255, 255, 255))
    assert is_blank_or_invalid_image(multi_color) is False


def test_ensure_desktop_access():
    # Should not crash on any platform
    res = ensure_desktop_access()
    assert isinstance(res, bool)


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


def test_get_screenshot_desktop_fallback():
    # Force capture_desktop_screenshot to return None
    with patch("execution.screenshot.capture_desktop_screenshot", return_value=None):
        png_bytes, caption = get_screenshot(fallback_terminal_text="Test prompt execution\n> Finished.")
        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 500
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "Terminal Screen Snapshot" in caption


def test_optimize_and_compress_image():
    # Large 2000x1200 image
    large = Image.new("RGB", (2000, 1200), color=(100, 150, 200))
    compressed_bytes = optimize_and_compress_image(large, max_dimension=1600, quality=85)
    assert isinstance(compressed_bytes, bytes)
    assert len(compressed_bytes) > 0
    # Check JPEG magic header
    assert compressed_bytes[:2] == b"\xff\xd8"

    # Verify resized dimension
    img = Image.open(io.BytesIO(compressed_bytes))
    assert max(img.width, img.height) <= 1600
    assert img.width == 1600
    assert img.height == 960


def test_get_screenshot_live():
    raw_bytes, caption = get_screenshot(fallback_terminal_text="Live Test\n> Success.")
    assert isinstance(raw_bytes, bytes)
    assert len(raw_bytes) > 500
    # Header should be JPEG or PNG
    assert raw_bytes[:2] == b"\xff\xd8" or raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    # Must be openable by PIL
    img = Image.open(io.BytesIO(raw_bytes))
    assert img.width > 0 and img.height > 0
    assert "Snapshot" in caption
