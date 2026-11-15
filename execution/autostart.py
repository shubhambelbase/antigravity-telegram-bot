"""Windows Auto-Start Manager for Antigravity Telegram Bot.

Allows the Telegram bot to launch silently in the background whenever
the user boots or logs in to their Windows laptop, using the standard
Windows Startup folder (%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup).
"""

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

SHORTCUT_NAME = "AntigravityTelegramBot.lnk"


def get_startup_folder() -> str:
    """Returns the user's Windows Startup directory."""
    return os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")


def get_startup_shortcut_path() -> str:
    """Returns the full path to the bot's auto-start shortcut."""
    return os.path.join(get_startup_folder(), SHORTCUT_NAME)


def is_autostart_enabled(shortcut_path: Optional[str] = None) -> bool:
    """Checks whether the auto-start shortcut currently exists in the Startup folder."""
    target = shortcut_path or get_startup_shortcut_path()
    return os.path.isfile(target)


def enable_autostart(
    project_dir: Optional[str] = None,
    shortcut_path: Optional[str] = None,
) -> bool:
    """Creates a Windows shortcut in the Startup folder to run start_bot_silent.vbs on login."""
    root = os.path.abspath(project_dir or os.path.dirname(os.path.dirname(__file__)))
    target_vbs = os.path.join(root, "setup", "start_bot_silent.vbs")
    if not os.path.isfile(target_vbs):
        target_vbs = os.path.join(root, "start_bot_silent.vbs")
    sc_dest = shortcut_path or get_startup_shortcut_path()

    if not os.path.isfile(target_vbs):
        logger.error(f"Cannot enable auto-start: {target_vbs} does not exist.")
        return False

    os.makedirs(os.path.dirname(sc_dest), exist_ok=True)

    # Use PowerShell COM object to create clean .lnk file
    ps_script = (
        f"$WshShell = New-Object -ComObject WScript.Shell; "
        f"$Shortcut = $WshShell.CreateShortcut('{sc_dest}'); "
        f"$Shortcut.TargetPath = 'wscript.exe'; "
        f"$Shortcut.Arguments = '\"{target_vbs}\"'; "
        f"$Shortcut.WorkingDirectory = '{root}'; "
        f"$Shortcut.WindowStyle = 7; "
        f"$Shortcut.Description = 'Antigravity Telegram Bot Auto-Start Remote Controller'; "
        f"$Shortcut.Save();"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and os.path.isfile(sc_dest):
            logger.info(f"Auto-start enabled successfully at: {sc_dest}")
            return True
        logger.error(f"Failed to create auto-start shortcut: {proc.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error enabling auto-start: {e}")
        return False


def disable_autostart(shortcut_path: Optional[str] = None) -> bool:
    """Removes the bot's auto-start shortcut from the Windows Startup folder."""
    sc_dest = shortcut_path or get_startup_shortcut_path()
    try:
        if os.path.isfile(sc_dest):
            os.remove(sc_dest)
            logger.info("Auto-start disabled successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to remove auto-start shortcut {sc_dest}: {e}")
        return False
