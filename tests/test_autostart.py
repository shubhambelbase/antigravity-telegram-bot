"""Unit tests for Windows Auto-Start Manager."""

import os
import pytest
from execution.autostart import (
    get_startup_folder,
    get_startup_shortcut_path,
    is_autostart_enabled,
    enable_autostart,
    disable_autostart,
)


def test_autostart_paths():
    folder = get_startup_folder()
    assert "Startup" in folder
    assert os.path.isabs(folder)

    sc_path = get_startup_shortcut_path()
    assert sc_path.endswith(".lnk")
    assert "AntigravityTelegramBot" in sc_path


def test_enable_and_disable_autostart(tmp_path):
    # Setup mock project directory with start_bot_silent.vbs
    mock_proj = tmp_path / "project"
    mock_proj.mkdir()
    vbs_file = mock_proj / "start_bot_silent.vbs"
    vbs_file.write_text("' mock vbs launcher\n", encoding="utf-8")

    mock_sc = tmp_path / "Startup" / "AntigravityTelegramBot.lnk"

    # Initially not enabled
    assert not is_autostart_enabled(shortcut_path=str(mock_sc))

    # Enable auto-start
    success = enable_autostart(project_dir=str(mock_proj), shortcut_path=str(mock_sc))
    assert success is True
    assert os.path.isfile(str(mock_sc))
    assert is_autostart_enabled(shortcut_path=str(mock_sc)) is True

    # Disable auto-start
    disabled = disable_autostart(shortcut_path=str(mock_sc))
    assert disabled is True
    assert not os.path.isfile(str(mock_sc))
    assert is_autostart_enabled(shortcut_path=str(mock_sc)) is False
