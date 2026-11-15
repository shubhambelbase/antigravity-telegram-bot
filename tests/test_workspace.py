"""Unit tests for workspace navigation and views."""

import os
from execution.agy_runner import AntigravityRunner
from execution.telegram_bot import build_workspace_view, build_drives_view


def test_build_workspace_view(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    (tmp_path / "project1").mkdir()
    (tmp_path / "project2").mkdir()

    text, markup = build_workspace_view(runner)
    assert str(tmp_path) in text
    assert markup.inline_keyboard is not None
    # Check that child folders are in keyboard buttons
    button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("project1" in btn for btn in button_texts)
    assert any("project2" in btn for btn in button_texts)
    assert any("Drives" in btn for btn in button_texts)
    assert any("Refresh" in btn for btn in button_texts)


def test_build_drives_view(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    text, markup = build_drives_view(runner)
    assert "Drives" in text
    button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("Back to Workspace" in btn for btn in button_texts)
