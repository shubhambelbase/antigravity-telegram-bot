"""Transcript Live Watcher.

Monitors Antigravity conversation transcript.jsonl in real-time,
detecting tool calls, thinking steps, user prompts, and responses,
and mirroring them to Telegram with live terminal-like bullets.
"""

import asyncio
import html
import json
import logging
import os
import re
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)


def extract_clean_user_content(raw: str) -> str:
    """Extracts actual prompt text from raw transcript input."""
    if "<USER_REQUEST>" in raw:
        try:
            return raw.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
        except IndexError:
            pass
    return raw.strip()


def format_tool_call(tc: dict) -> str:
    """Formats a tool call into a terminal-like bullet with safe HTML escaping."""
    name = tc.get("name", "tool")
    args = tc.get("args", {})
    if not isinstance(args, dict):
        args = {}

    if name == "run_command":
        summary = str(args.get("toolSummary", "")).strip('\"\'')
        cmd = str(args.get("CommandLine", "")).strip('\"\'')
        label = html.escape(summary or cmd[:50])
        return f"● Ran: <code>{label}</code>"
    elif name == "edit_file":
        p = str(args.get("Path", "")).strip('\"\'')
        fname = html.escape(os.path.basename(p) or p)
        return f"● Edited: <code>{fname}</code>"
    elif name == "write_file":
        p = str(args.get("Path", "")).strip('\"\'')
        fname = html.escape(os.path.basename(p) or p)
        return f"● Created: <code>{fname}</code>"
    elif name == "read_file":
        p = str(args.get("Path", "")).strip('\"\'')
        fname = html.escape(os.path.basename(p) or p)
        return f"● Read: <code>{fname}</code>"
    elif name == "manage_task":
        action = html.escape(str(args.get("Action", "")).strip('\"\''))
        tid = html.escape(str(args.get("TaskId", "")).strip('\"\'').split("/")[-1])
        return f"● Task: <code>{action} {tid}</code>".strip()
    elif name == "search_web":
        q = html.escape(str(args.get("query", "")).strip('\"\'')[:40])
        return f"● Search: <code>{q}</code>"
    else:
        escaped_name = html.escape(name)
        return f"● Tool: <code>{escaped_name}</code>"


def format_thinking(thinking_text: str) -> Optional[str]:
    """Formats thinking trace into a concise bullet with safe HTML escaping."""
    if not thinking_text or not thinking_text.strip():
        return None
    # Pick first non-empty line
    lines = [line.strip() for line in thinking_text.splitlines() if line.strip()]
    if not lines:
        return None
    summary = lines[0]
    if len(summary) > 75:
        summary = summary[:72] + "..."
    escaped_summary = html.escape(summary)
    return f"○ Thought: <i>{escaped_summary}</i>"


class TranscriptWatcher:
    def __init__(
        self,
        brain_dir: str,
        get_active_conv_id: Callable[[], Optional[str]],
        is_bot_running: Callable[[], bool],
        on_user_turn: Callable[[str, str], Awaitable[None]],
        on_model_turn: Callable[[str, str, List[str]], Awaitable[None]],
        on_activity_step: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ):
        self.brain_dir = brain_dir
        self.get_active_conv_id = get_active_conv_id
        self.is_bot_running = is_bot_running
        self.on_user_turn = on_user_turn
        self.on_model_turn = on_model_turn
        self.on_activity_step = on_activity_step
        self._running = False
        self.is_enabled = True
        self._task: Optional[asyncio.Task] = None
        self._current_conv_id: Optional[str] = None
        self._last_offset = 0
        self._last_step_index = -1
        self._current_turn_bullets: List[str] = []

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._watch_loop())
            logger.info("TranscriptWatcher started.")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("TranscriptWatcher stopped.")

    def pause(self):
        """Pauses live PC sync mirroring to Telegram."""
        self.is_enabled = False
        logger.info("TranscriptWatcher paused (live sync disabled).")

    def resume(self):
        """Resumes live PC sync mirroring, fast-forwarding past backlog."""
        self.is_enabled = True
        conv_id = self.get_active_conv_id()
        if conv_id:
            path = self._get_transcript_path(conv_id)
            if os.path.isfile(path):
                self._last_offset = os.path.getsize(path)
        logger.info("TranscriptWatcher resumed (live sync enabled).")

    def _get_transcript_path(self, conv_id: str) -> str:
        return os.path.join(self.brain_dir, conv_id, ".system_generated", "logs", "transcript.jsonl")

    async def _init_tracking_for_conv(self, conv_id: str):
        self._current_conv_id = conv_id
        path = self._get_transcript_path(conv_id)
        self._last_offset = 0
        self._last_step_index = -1
        self._current_turn_bullets = []

        if os.path.isfile(path):
            try:
                # Seek to end of file so we only stream NEW events going forward
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip():
                            try:
                                data = json.loads(line)
                                step = data.get("step_index", -1)
                                if step > self._last_step_index:
                                    self._last_step_index = step
                            except Exception:
                                pass
                    self._last_offset = f.tell()
                logger.info(f"Initialized watcher on session {conv_id} at step {self._last_step_index}")
            except Exception as e:
                logger.warning(f"Error initializing transcript tracking: {e}")

    async def _watch_loop(self):
        while self._running:
            try:
                if not self.is_enabled:
                    await asyncio.sleep(1.0)
                    continue

                conv_id = self.get_active_conv_id()
                if not conv_id:
                    await asyncio.sleep(1.0)
                    continue

                if conv_id != self._current_conv_id:
                    await self._init_tracking_for_conv(conv_id)

                path = self._get_transcript_path(conv_id)
                if not os.path.isfile(path):
                    await asyncio.sleep(1.0)
                    continue

                current_size = os.path.getsize(path)
                if current_size < self._last_offset:
                    self._last_offset = 0
                    self._last_step_index = -1
                    self._current_turn_bullets = []

                if current_size > self._last_offset:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._last_offset)
                        new_lines = f.readlines()
                        if new_lines and not new_lines[-1].endswith("\n"):
                            incomplete = new_lines.pop()
                            # Rewind offset by the incomplete line's byte length so it will be read completely once flushed
                            self._last_offset = f.tell() - len(incomplete.encode("utf-8", errors="replace"))
                        else:
                            self._last_offset = f.tell()

                    for line in new_lines:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            step_index = record.get("step_index", -1)
                            if step_index <= self._last_step_index:
                                continue
                            self._last_step_index = step_index

                            # Skip if headless bot turn
                            if self.is_bot_running():
                                continue

                            source = record.get("source")
                            rec_type = record.get("type")
                            content = record.get("content", "")

                            # 1. User Prompt
                            if source == "USER_EXPLICIT" and rec_type == "USER_INPUT":
                                self._current_turn_bullets = []
                                clean_prompt = extract_clean_user_content(content)
                                if clean_prompt:
                                    await self.on_user_turn(conv_id, clean_prompt)

                            # 2. Model Thoughts & Tool Calls
                            elif source == "MODEL" and rec_type == "PLANNER_RESPONSE":
                                thinking = record.get("thinking", "")
                                th_bullet = format_thinking(thinking)
                                if th_bullet:
                                    self._current_turn_bullets.append(th_bullet)
                                    if self.on_activity_step:
                                        await self.on_activity_step(conv_id, th_bullet)

                                tool_calls = record.get("tool_calls", [])
                                for tc in tool_calls:
                                    tc_bullet = format_tool_call(tc)
                                    self._current_turn_bullets.append(tc_bullet)
                                    if self.on_activity_step:
                                        await self.on_activity_step(conv_id, tc_bullet)

                                # If this planner response contains final user-facing text
                                if content and content.strip():
                                    await self.on_model_turn(
                                        conv_id,
                                        content.strip(),
                                        list(self._current_turn_bullets),
                                    )
                                    self._current_turn_bullets = []

                        except Exception as parse_err:
                            logger.debug(f"Failed to parse transcript line: {parse_err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in transcript watcher loop: {e}", exc_info=True)

            await asyncio.sleep(1.0)
