import asyncio
import json
import pytest
from execution.transcript_watcher import (
    TranscriptWatcher,
    extract_clean_user_content,
    format_tool_call,
    format_thinking,
)


def test_extract_clean_user_content():
    raw = "<USER_REQUEST>\nhello world\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime=123\n</ADDITIONAL_METADATA>"
    assert extract_clean_user_content(raw) == "hello world"


def test_format_tool_call():
    tc_run = {
        "name": "run_command",
        "args": {"CommandLine": "python test.py", "toolSummary": "Run unit test"}
    }
    assert "● Ran: <code>Run unit test</code>" == format_tool_call(tc_run)

    # Test HTML escaping of <, >, and &
    tc_html = {
        "name": "run_command",
        "args": {"CommandLine": "cat < input.txt && echo > out.txt", "toolSummary": "Check <tag> & output"}
    }
    formatted = format_tool_call(tc_html)
    assert "&lt;tag&gt;" in formatted
    assert "&amp;" in formatted

    tc_edit = {"name": "edit_file", "args": {"Path": "E:/test/script.py"}}
    assert "● Edited: <code>script.py</code>" == format_tool_call(tc_edit)


def test_format_thinking():
    th = "Analyzing dependencies and file structure.\nDetails..."
    assert "○ Thought: <i>Analyzing dependencies and file structure.</i>" == format_thinking(th)

    # Test HTML escaping in thinking
    th_special = "Comparing if count < 10 && val > 0"
    formatted_th = format_thinking(th_special)
    assert "&lt;" in formatted_th
    assert "&gt;" in formatted_th
    assert "&amp;" in formatted_th


def test_transcript_watcher_detection(tmp_path):
    async def run_test():
        conv_id = "test-conv-123"
        logs_dir = tmp_path / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        transcript_file = logs_dir / "transcript.jsonl"

        user_turns = []
        model_turns = []
        activity_steps = []

        async def on_user(c_id, text):
            user_turns.append((c_id, text))

        async def on_model(c_id, content, bullets):
            model_turns.append((c_id, content, bullets))

        async def on_act(c_id, bullet):
            activity_steps.append((c_id, bullet))

        watcher = TranscriptWatcher(
            brain_dir=str(tmp_path),
            get_active_conv_id=lambda: conv_id,
            is_bot_running=lambda: False,
            on_user_turn=on_user,
            on_model_turn=on_model,
            on_activity_step=on_act,
        )
        watcher.start()
        await asyncio.sleep(0.3)

        # 1. Append user prompt
        with open(transcript_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>\nFix bug in script.py\n</USER_REQUEST>"
            }) + "\n")

        await asyncio.sleep(1.2)

        # 2. Append tool call step
        with open(transcript_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "thinking": "Inspecting script.py line 42",
                "tool_calls": [{"name": "edit_file", "args": {"Path": "script.py"}}],
                "content": "Bug fixed."
            }) + "\n")

        await asyncio.sleep(1.2)
        watcher.stop()

        assert len(user_turns) == 1
        assert len(activity_steps) == 2  # 1 thought + 1 tool call
        assert len(model_turns) == 1
        assert model_turns[0][1] == "Bug fixed."
        assert len(model_turns[0][2]) == 2

    asyncio.run(run_test())


def test_transcript_watcher_pause_resume(tmp_path):
    async def run_test():
        conv_id = "test-conv-pause"
        logs_dir = tmp_path / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        transcript_file = logs_dir / "transcript.jsonl"

        received = []
        async def on_act(c_id, bullet):
            received.append(bullet)

        watcher = TranscriptWatcher(
            brain_dir=str(tmp_path),
            get_active_conv_id=lambda: conv_id,
            is_bot_running=lambda: False,
            on_user_turn=lambda c, t: None,
            on_model_turn=lambda c, co, b: None,
            on_activity_step=on_act,
        )
        assert watcher.is_enabled is True
        watcher.pause()
        assert watcher.is_enabled is False
        watcher.resume()
        assert watcher.is_enabled is True

    asyncio.run(run_test())


def test_transcript_watcher_partial_line_handling(tmp_path):
    async def run_test():
        conv_id = "test-conv-partial"
        logs_dir = tmp_path / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        transcript_file = logs_dir / "transcript.jsonl"

        user_turns = []
        async def on_user(c_id, text):
            user_turns.append((c_id, text))

        watcher = TranscriptWatcher(
            brain_dir=str(tmp_path),
            get_active_conv_id=lambda: conv_id,
            is_bot_running=lambda: False,
            on_user_turn=on_user,
            on_model_turn=lambda c, co, b: None,
        )
        watcher.start()
        await asyncio.sleep(0.3)

        # 1. Write an INCOMPLETE line (simulating write in progress without trailing \n)
        full_json = json.dumps({
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "content": "<USER_REQUEST>\nExecute build\n</USER_REQUEST>"
        })
        split_idx = len(full_json) // 2
        with open(transcript_file, "a", encoding="utf-8") as f:
            f.write(full_json[:split_idx])  # No newline

        await asyncio.sleep(1.2)
        # Should not have processed yet because line is incomplete
        assert len(user_turns) == 0

        # 2. Complete the line with newline
        with open(transcript_file, "a", encoding="utf-8") as f:
            f.write(full_json[split_idx:] + "\n")

        await asyncio.sleep(1.2)
        watcher.stop()

        # Now it must be successfully parsed without corruption or dropping!
        assert len(user_turns) == 1
        assert user_turns[0][1] == "Execute build"

    asyncio.run(run_test())
