import os
import pytest
from execution.agy_runner import AntigravityRunner


def test_runner_initialization():
    runner = AntigravityRunner(default_workspace=os.getcwd())
    assert runner.workspace_dir == os.getcwd()
    assert runner.is_running is False
    assert runner.conversation_id is None


def test_runner_set_workspace(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    assert runner.workspace_dir == str(tmp_path)

    new_dir = tmp_path / "subproject"
    new_dir.mkdir()
    assert runner.set_workspace(str(new_dir)) is True
    assert runner.workspace_dir == str(new_dir)

    assert runner.set_workspace(str(tmp_path / "non_existent")) is False


def test_runner_reset_conversation():
    runner = AntigravityRunner()
    runner.conversation_id = "test-session-123"
    runner.reset_conversation()
    assert runner.conversation_id is None


def test_runner_get_recent_conversations():
    runner = AntigravityRunner()
    recents = runner.get_recent_conversations(limit=3)
    assert isinstance(recents, list)
    if recents:
        assert hasattr(recents[0], "conv_id")
        assert hasattr(recents[0], "preview")
        assert hasattr(recents[0], "updated_at")


def test_runner_get_session_turns_and_logs(tmp_path):
    runner = AntigravityRunner()
    # Test on non-existent session
    turns = runner.get_session_turns("fake-uuid-not-exist")
    assert turns == []

    logs = runner.get_session_log_export("fake-uuid-not-exist")
    assert "not found" in logs.lower()
