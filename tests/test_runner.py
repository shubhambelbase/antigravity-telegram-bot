import os
import pytest
from execution.agy_runner import AntigravityRunner


def test_runner_initialization():
    runner = AntigravityRunner(default_workspace=os.getcwd())
    assert runner.workspace_dir == os.path.abspath(os.getcwd())
    assert runner.is_running is False
    assert runner.conversation_id is None
    assert runner.workspace_dir in runner.recent_workspaces


def test_runner_set_workspace(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    assert runner.workspace_dir == str(tmp_path)

    new_dir = tmp_path / "subproject"
    new_dir.mkdir()
    # Test absolute path
    assert runner.set_workspace(str(new_dir)) is True
    assert runner.workspace_dir == str(new_dir)

    # Test relative path '..'
    assert runner.set_workspace("..") is True
    assert runner.workspace_dir == str(tmp_path)

    # Test relative subfolder
    assert runner.set_workspace("subproject") is True
    assert runner.workspace_dir == str(new_dir)

    assert runner.set_workspace(str(tmp_path / "non_existent")) is False


def test_runner_create_and_set_workspace(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    created = runner.create_and_set_workspace("brand_new_dir")
    assert created is True
    assert os.path.isdir(str(tmp_path / "brand_new_dir"))
    assert runner.workspace_dir == str(tmp_path / "brand_new_dir")


def test_runner_workspace_subdirs_and_parent(tmp_path):
    runner = AntigravityRunner(default_workspace=str(tmp_path))
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / ".hidden").mkdir()

    subdirs = runner.get_workspace_subdirs()
    assert "alpha" in subdirs
    assert "beta" in subdirs
    assert ".hidden" not in subdirs

    parent = runner.get_parent_workspace()
    assert parent == str(tmp_path.parent)

    drives = runner.get_available_drives()
    assert isinstance(drives, list)
    assert len(drives) > 0


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


def test_runner_conversation_mtime_prioritizes_transcript(tmp_path):
    brain = tmp_path / "brain"
    brain.mkdir()

    # Old folder with brand new transcript
    conv1 = brain / "conv-older-folder"
    conv1.mkdir()
    t1_dir = conv1 / ".system_generated" / "logs"
    t1_dir.mkdir(parents=True)
    t1_file = t1_dir / "transcript.jsonl"
    t1_file.write_text('{"step_index": 0}\n', encoding="utf-8")

    # Newer folder with older transcript
    conv2 = brain / "conv-newer-folder"
    conv2.mkdir()
    t2_dir = conv2 / ".system_generated" / "logs"
    t2_dir.mkdir(parents=True)
    t2_file = t2_dir / "transcript.jsonl"
    t2_file.write_text('{"step_index": 0}\n', encoding="utf-8")

    # Set explicit timestamps: conv1 transcript is newest (t=2000), conv2 folder is newer (t=1500)
    os.utime(t2_file, (1000, 1000))
    os.utime(conv2, (1500, 1500))
    os.utime(conv1, (500, 500))
    os.utime(t1_file, (2000, 2000))

    runner = AntigravityRunner()
    runner.brain_dir = str(brain)

    latest = runner._get_latest_conversation_id()
    assert latest == "conv-older-folder"

    recents = runner.get_recent_conversations(limit=2)
    assert len(recents) == 2
    assert recents[0].conv_id == "conv-older-folder"
    assert recents[1].conv_id == "conv-newer-folder"
