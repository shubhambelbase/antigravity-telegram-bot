"""Screenshot capture utility for Windows desktop and terminal display.

Supports physical desktop screen capture (via PIL ImageGrab / Win32)
and high-fidelity terminal window image rendering fallback.
"""

import base64
import io
import logging
import os
import subprocess
from typing import Optional, Tuple
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


def capture_desktop_screenshot() -> Optional[bytes]:
    """Attempts to capture the physical desktop screen using PIL or PowerShell."""
    # Method 1: PIL ImageGrab (works in interactive user sessions)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        if img:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        logger.debug(f"PIL ImageGrab not available in current session: {e}")

    # Method 2: PowerShell Graphics.CopyFromScreen
    try:
        ps_code = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
            "$ms = New-Object System.IO.MemoryStream; "
            "$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); "
            "[System.Convert]::ToBase64String($ms.ToArray()); "
            "$g.Dispose(); $bmp.Dispose(); $ms.Dispose();"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_b64 = res.stdout.strip()
            return base64.b64decode(raw_b64)
    except Exception as e:
        logger.debug(f"PowerShell screen copy failed: {e}")

    return None


def render_terminal_snapshot(terminal_text: str, title: str = "Antigravity Live Terminal") -> bytes:
    """Renders a dark-mode terminal window snapshot image with macOS/Linux titlebar controls."""
    lines = [line.rstrip() for line in terminal_text.splitlines() if line.strip()]
    if not lines:
        lines = [
            "Antigravity Live Terminal Session Active",
            "> Ready for commands...",
            "",
            "(No active stdout logs at this moment)",
        ]

    # Keep last 35 lines to fit cleanly
    display_lines = lines[-35:]
    width = 960
    line_height = 22
    header_height = 42
    padding = 20
    height = max(320, header_height + len(display_lines) * line_height + padding * 2)

    img = Image.new("RGB", (width, height), color=(24, 24, 28))
    draw = ImageDraw.Draw(img)

    # Window titlebar
    draw.rectangle([0, 0, width, header_height], fill=(36, 36, 42))
    # Window controls (red/yellow/green dots)
    draw.ellipse([16, 15, 28, 27], fill=(255, 95, 86))
    draw.ellipse([36, 15, 48, 27], fill=(255, 189, 46))
    draw.ellipse([56, 15, 68, 27], fill=(39, 201, 63))

    # Title text
    draw.text((85, 13), f"● {title}", fill=(200, 205, 215))

    # Render terminal output lines with syntax color hints
    y = header_height + padding
    for line in display_lines:
        line_clean = line[:110]
        if line_clean.startswith("● Ran:"):
            fill_color = (130, 220, 255)
        elif line_clean.startswith("● Edited:") or line_clean.startswith("● Created:"):
            fill_color = (140, 240, 160)
        elif line_clean.startswith("○ Thought:"):
            fill_color = (255, 215, 120)
        elif line_clean.startswith("❌") or "error" in line_clean.lower():
            fill_color = (255, 120, 120)
        elif line_clean.startswith(">"):
            fill_color = (180, 230, 255)
        else:
            fill_color = (220, 225, 230)

        draw.text((padding, y), line_clean, fill=fill_color)
        y += line_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_screenshot(fallback_terminal_text: Optional[str] = None, title: str = "Antigravity Live Terminal") -> Tuple[bytes, str]:
    """Returns (png_bytes, caption_description)."""
    raw_desktop = capture_desktop_screenshot()
    if raw_desktop and len(raw_desktop) > 1000:
        return raw_desktop, "🖥️ Desktop Screen Snapshot"

    # Fallback to high-fidelity dark-mode terminal snapshot
    text = fallback_terminal_text or "Antigravity Live Terminal\nStatus: Online / Ready\n"
    rendered = render_terminal_snapshot(text, title=title)
    return rendered, "📺 Terminal Screen Snapshot (Visual Render)"
