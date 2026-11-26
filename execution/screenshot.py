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
import textwrap
from typing import Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_desktop_station_attached = False


def _get_current_desktop_name() -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        user32.GetThreadDesktop.restype = wintypes.HANDLE
        user32.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetUserObjectInformationW.restype = wintypes.BOOL

        hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        if not hdesk:
            return None
        buf = ctypes.create_unicode_buffer(128)
        needed = wintypes.DWORD()
        # UOI_NAME = 2
        if user32.GetUserObjectInformationW(hdesk, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
            return buf.value
    except Exception:
        pass
    return None


def ensure_desktop_access() -> bool:
    """Attaches current process and thread to WinSta0 (interactive window station) and default desktop safely."""
    global _desktop_station_attached
    if os.name != "nt":
        return False
    if _desktop_station_attached and (_get_current_desktop_name() or "").lower() == "default":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        user32.OpenWindowStationW.restype = wintypes.HANDLE
        user32.SetProcessWindowStation.argtypes = [wintypes.HANDLE]
        user32.SetProcessWindowStation.restype = wintypes.BOOL
        user32.CloseWindowStation.argtypes = [wintypes.HANDLE]
        user32.CloseWindowStation.restype = wintypes.BOOL

        user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenDesktopW.restype = wintypes.HANDLE
        user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        user32.SetThreadDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL

        # WINSTA_ALL_ACCESS = 0x0000037F
        hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x0000037F)
        if hwinsta:
            try:
                user32.SetProcessWindowStation(hwinsta)
            finally:
                user32.CloseWindowStation(hwinsta)

        # DESKTOP_ALL_ACCESS = 0x01FF
        hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hdesk:
            try:
                user32.SetThreadDesktop(hdesk)
            finally:
                user32.CloseDesktop(hdesk)

        _desktop_station_attached = True
        return True
    except Exception as e:
        logger.debug(f"Failed to attach to WinSta0 desktop: {e}")
        return False


def is_blank_or_invalid_image(img: Optional[Image.Image]) -> bool:
    """Checks whether an image is completely transparent, single solid color (e.g. solid white/black), or invalid."""
    if img is None or img.width <= 1 or img.height <= 1:
        return True

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        try:
            extrema = img.getextrema()
            if img.mode == "RGBA":
                alpha_extrema = extrema[3]
                if alpha_extrema[1] == 0:
                    return True
        except Exception:
            pass

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

        ensure_desktop_access()

        left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
        width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN

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


def optimize_and_compress_image(
    img: Image.Image,
    max_dimension: int = 1600,
    quality: int = 85,
    format: str = "JPEG",
) -> bytes:
    """Resizes large images preserving aspect ratio and compresses to optimized bytes (JPEG or PNG)."""
    width, height = img.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / max(width, height)
        new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize(new_size, resample=resample)

    buf = io.BytesIO()
    if format.upper() in ("JPEG", "JPG"):
        rgb_img = img.convert("RGB")
        rgb_img.save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def capture_desktop_screenshot() -> Optional[bytes]:
    """Attempts to capture physical desktop screen with blank/transparency validation and compression."""
    ensure_desktop_access()

    # Method 1: PIL ImageGrab
    try:
        from PIL import ImageGrab
        img = None
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = ImageGrab.grab()

        if img and not is_blank_or_invalid_image(img):
            return optimize_and_compress_image(img, max_dimension=1600, quality=85)
    except Exception as e:
        logger.debug(f"PIL ImageGrab not available or blank: {e}")

    # Method 2: Win32 GDI BitBlt capture
    try:
        win_img = capture_win32_gdi()
        if win_img and not is_blank_or_invalid_image(win_img):
            return optimize_and_compress_image(win_img, max_dimension=1600, quality=85)
    except Exception as e:
        logger.debug(f"Win32 GDI capture failed or blank: {e}")

    # Method 3: PowerShell CopyFromScreen
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
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_b64 = res.stdout.strip()
            data = base64.b64decode(raw_b64)
            ps_img = Image.open(io.BytesIO(data))
            if not is_blank_or_invalid_image(ps_img):
                return optimize_and_compress_image(ps_img, max_dimension=1600, quality=85)
    except Exception as e:
        logger.debug(f"PowerShell screen copy failed or blank: {e}")

    return None


def _load_terminal_font(size: int = 15) -> Tuple[Any, bool]:
    """Loads a crisp monospace TrueType font when available, returning (font, is_truetype)."""
    candidates = [
        r"C:\Windows\Fonts\CascadiaMono.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        r"C:\Windows\Fonts\cour.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size), True
            except Exception:
                continue
    return ImageFont.load_default(), False


def render_terminal_snapshot(terminal_text: str, title: str = "Antigravity Live Terminal") -> bytes:
    """Renders a dark-mode terminal window snapshot image with macOS/Linux titlebar controls."""
    raw_lines = [line.rstrip() for line in terminal_text.splitlines() if line.strip()]
    if not raw_lines:
        raw_lines = [
            "Antigravity Live Terminal Session Active",
            "> Ready for commands...",
            "",
            "(No active stdout logs at this moment)",
        ]

    font, is_ttf = _load_terminal_font(size=15)
    title_font, _ = _load_terminal_font(size=14)

    wrapped_lines = []
    wrap_width = 96 if is_ttf else 108
    for line in raw_lines:
        if not line:
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(textwrap.wrap(line, width=wrap_width, break_long_words=True) or [line])

    display_lines = wrapped_lines[-35:]
    width = 960
    line_height = 22 if is_ttf else 18
    header_height = 42
    padding = 20
    height = max(320, header_height + len(display_lines) * line_height + padding * 2)

    img = Image.new("RGB", (width, height), color=(24, 24, 28))
    draw = ImageDraw.Draw(img)

    # Window titlebar
    draw.rectangle([0, 0, width, header_height], fill=(36, 36, 42))
    draw.ellipse([16, 15, 28, 27], fill=(255, 95, 86))
    draw.ellipse([36, 15, 48, 27], fill=(255, 189, 46))
    draw.ellipse([56, 15, 68, 27], fill=(39, 201, 63))

    title_prefix = "● " if is_ttf else "* "
    draw.text((85, 13), f"{title_prefix}{title}", fill=(200, 205, 215), font=title_font)

    y = header_height + padding
    for line in display_lines:
        line_clean = line
        if not is_ttf:
            # Replace symbols unsupported by Pillow's built-in bitmap font
            line_clean = (
                line_clean.replace("●", "*")
                .replace("○", "o")
                .replace("❌", "[ERR]")
                .replace("✅", "[OK]")
                .encode("latin-1", "replace")
                .decode("latin-1")
            )

        if line.startswith("● Ran:") or line.startswith("* Ran:"):
            fill_color = (130, 220, 255)
        elif line.startswith("● Edited:") or line.startswith("● Created:"):
            fill_color = (140, 240, 160)
        elif line.startswith("○ Thought:"):
            fill_color = (255, 215, 120)
        elif line.startswith("❌") or "error" in line.lower():
            fill_color = (255, 120, 120)
        elif line.startswith(">"):
            fill_color = (180, 230, 255)
        else:
            fill_color = (220, 225, 230)

        draw.text((padding, y), line_clean, fill=fill_color, font=font)
        y += line_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_screenshot(fallback_terminal_text: Optional[str] = None, title: str = "Antigravity Live Terminal") -> Tuple[bytes, str]:
    """Returns (png_bytes, caption_description)."""
    raw_desktop = capture_desktop_screenshot()
    if raw_desktop and len(raw_desktop) > 1000:
        return raw_desktop, "🖥️ Desktop Screen Snapshot"

    text = fallback_terminal_text or "Antigravity Live Terminal\nStatus: Online / Ready\n"
    rendered = render_terminal_snapshot(text, title=title)
    return rendered, "📺 Terminal Screen Snapshot (Visual Render)"
