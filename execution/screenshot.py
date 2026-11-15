"""Screenshot capture utility for Windows desktop and terminal display.

Supports physical desktop screen capture (via WinSta0 desktop attachment,
PIL ImageGrab, and Win32 GDI BitBlt) with blank/transparency validation
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


def ensure_desktop_access() -> bool:
    """Attaches current process and thread to WinSta0 (interactive window station) and default desktop."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # WINSTA_ALL_ACCESS = 0x0000037F
        hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x0000037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
        # DESKTOP_ALL_ACCESS = 0x01FF
        hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
        return True
    except Exception as e:
        logger.debug(f"Failed to attach to WinSta0 desktop: {e}")
        return False


def is_blank_or_invalid_image(img: Optional[Image.Image]) -> bool:
    """Checks whether an image is completely transparent, single solid color (e.g. solid white/black), or invalid."""
    if img is None or img.width <= 1 or img.height <= 1:
        return True

    # Check for complete transparency
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        try:
            extrema = img.getextrema()
            if img.mode == "RGBA":
                alpha_extrema = extrema[3]
                if alpha_extrema[1] == 0:  # Max alpha is 0 => completely transparent
                    return True
        except Exception:
            pass

    # Check for solid single-color images (e.g. solid white or solid black)
    try:
        rgb = img.convert("RGB")
        colors = rgb.getcolors(maxcolors=2)
        if colors is not None and len(colors) == 1:
            return True
    except Exception:
        pass

    return False


def capture_win32_gdi() -> Optional[Image.Image]:
    """Captures the virtual or primary desktop screen via Win32 GDI BitBlt."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # Attach to interactive desktop station
        ensure_desktop_access()

        # Query virtual screen coordinates
        left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        top = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        width = user32.GetSystemMetrics(78) # SM_CXVIRTUALSCREEN
        height = user32.GetSystemMetrics(79)# SM_CYVIRTUALSCREEN

        if width <= 0 or height <= 0:
            left = 0
            top = 0
            width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            height = user32.GetSystemMetrics(1) # SM_CYSCREEN

        if width <= 0 or height <= 0:
            return None

        hdesktop_dc = user32.GetDC(0)
        if not hdesktop_dc:
            return None

        try:
            hmem_dc = gdi32.CreateCompatibleDC(hdesktop_dc)
            if not hmem_dc:
                return None

            hbitmap = gdi32.CreateCompatibleBitmap(hdesktop_dc, width, height)
            if not hbitmap:
                gdi32.DeleteDC(hmem_dc)
                return None

            hold_bmp = gdi32.SelectObject(hmem_dc, hbitmap)
            raster_op = 0x00CC0020  # SRCCOPY
            success = gdi32.BitBlt(hmem_dc, 0, 0, width, height, hdesktop_dc, left, top, raster_op)
            if not success:
                gdi32.SelectObject(hmem_dc, hold_bmp)
                gdi32.DeleteObject(hbitmap)
                gdi32.DeleteDC(hmem_dc)
                return None

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height  # top-down DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0   # BI_RGB

            buf_size = width * height * 4
            buffer = ctypes.create_string_buffer(buf_size)
            res = gdi32.GetDIBits(hmem_dc, hbitmap, 0, height, buffer, ctypes.byref(bmi), 0)

            # Cleanup GDI handles
            gdi32.SelectObject(hmem_dc, hold_bmp)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hmem_dc)

            if res == 0:
                return None

            img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
            return img.convert("RGB")
        finally:
            user32.ReleaseDC(0, hdesktop_dc)
    except Exception as e:
        logger.debug(f"Win32 BitBlt capture failed: {e}")
        return None


def capture_desktop_screenshot() -> Optional[bytes]:
    """Attempts to capture physical desktop screen with blank/transparency validation."""
    ensure_desktop_access()

    # Method 1: PIL ImageGrab (with WinSta0 attachment)
    try:
        from PIL import ImageGrab
        img = None
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = ImageGrab.grab()

        if img and not is_blank_or_invalid_image(img):
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        logger.debug(f"PIL ImageGrab not available or blank: {e}")

    # Method 2: Win32 GDI BitBlt capture
    try:
        win_img = capture_win32_gdi()
        if win_img and not is_blank_or_invalid_image(win_img):
            buf = io.BytesIO()
            win_img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        logger.debug(f"Win32 GDI capture failed or blank: {e}")

    # Method 3: PowerShell CopyFromScreen (with strict ErrorAction and validation)
    try:
        ps_code = (
            "$ErrorActionPreference = 'Stop'; "
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
            data = base64.b64decode(raw_b64)
            ps_img = Image.open(io.BytesIO(data))
            if not is_blank_or_invalid_image(ps_img):
                return data
    except Exception as e:
        logger.debug(f"PowerShell screen copy failed or blank: {e}")

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
