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
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

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

    def _pick_path() -> str:
        for key in ("Path", "TargetFile", "path", "file_path", "AbsolutePath", "DirectoryPath", "SearchDirectory"):
            val = args.get(key)
            if val:
                return str(val).strip("\"'")
        return ""

    if name == "run_command":
        summary = str(args.get("toolSummary", "")).strip("\"'")
        cmd = str(args.get("CommandLine", "")).strip("\"'")
        label = html.escape(summary or cmd[:50])
        return f"● Ran: <code>{label}</code>"
    elif name in ("edit_file", "replace_file_content", "multi_replace_file_content"):
        p = _pick_path()
        fname = html.escape(os.path.basename(p) or p or name)
        return f"● Edited: <code>{fname}</code>"
    elif name in ("write_file", "write_to_file"):
        p = _pick_path()
        fname = html.escape(os.path.basename(p) or p or name)
        return f"● Created: <code>{fname}</code>"
    elif name in ("read_file", "view_file", "view_file_outline", "view_code_item"):
        p = _pick_path()
        fname = html.escape(os.path.basename(p) or p or name)
        return f"● Read: <code>{fname}</code>"
    elif name in ("grep_search", "find_by_name", "list_dir"):
        q = str(args.get("Query") or args.get("Pattern") or _pick_path() or "").strip("\"'")[:40]
        return f"● Search: <code>{html.escape(q or name)}</code>"
    elif name == "manage_task":
        action = html.escape(str(args.get("Action", "")).strip("\"'"))
        tid = html.escape(str(args.get("TaskId", "")).strip("\"'").split("/")[-1])
        return f"● Task: <code>{action} {tid}</code>".strip()
    elif name == "search_web":
        q = html.escape(str(args.get("query", "")).strip("\"'")[:40])
        return f"● Search: <code>{q}</code>"
    elif name == "invoke_subagent":
        role = html.escape(str(args.get("Role") or args.get("TypeName") or "subagent").strip("\"'")[:40])
        return f"● Subagent: <code>{role}</code>"
    else:
        escaped_name = html.escape(name)
        return f"● Tool: <code>{escaped_name}</code>"


def format_thinking(thinking_text: str) -> Optional[str]:
    """Formats thinking trace into a concise bullet with safe HTML escaping."""
    if not thinking_text or not thinking_text.strip():
        return None
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
        # Per-conversation state prevents cursor thrashing and duplicate replays when multiple sessions run
        self._conv_states: Dict[str, Dict[str, Any]] = {}

    def _get_state(self, conv_id: str) -> Dict[str, Any]:
        if conv_id not in self._conv_states:
            self._conv_states[conv_id] = {
                "offset": 0,
                "step_index": -1,
                "bullets": [],
                "initialized": False,
            }
        return self._conv_states[conv_id]

    @property
    def _last_offset(self) -> int:
        if self._current_conv_id and self._current_conv_id in self._conv_states:
            return self._conv_states[self._current_conv_id]["offset"]
        return 0

    @property
    def _last_step_index(self) -> int:
        if self._current_conv_id and self._current_conv_id in self._conv_states:
            return self._conv_states[self._current_conv_id]["step_index"]
        return -1

    @property
    def _current_turn_bullets(self) -> List[str]:
        if self._current_conv_id and self._current_conv_id in self._conv_states:
            return self._conv_states[self._current_conv_id]["bullets"]
        return []

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
        """Resumes live PC sync mirroring, fast-forwarding past backlog cleanly."""
        self.is_enabled = True
        conv_id = self.get_active_conv_id()
        if conv_id:
            state = self._get_state(conv_id)
            path = self._get_transcript_path(conv_id)
            if os.path.isfile(path):
                end_offset, highest_step = self._scan_eof_state(path)
                state["offset"] = end_offset
                if highest_step > state["step_index"]:
                    state["step_index"] = highest_step
            state["bullets"] = []
            state["initialized"] = True
        logger.info("TranscriptWatcher resumed (live sync enabled).")

    def _get_transcript_path(self, conv_id: str) -> str:
        return os.path.join(self.brain_dir, conv_id, ".system_generated", "logs", "transcript.jsonl")

    async def switch_to_conv(self, conv_id: str):
        """Switches active tracked conversation; initializes cursor only if not previously tracked."""
        if not conv_id:
            return
        self._current_conv_id = conv_id
        state = self._get_state(conv_id)
        if not state["initialized"]:
            await self._init_tracking_for_conv(conv_id)

    async def mark_conv_caught_up(self, conv_id: Optional[str]):
        """Advances cursor to EOF for a conversation after a headless bot turn to prevent duplicate mirroring."""
        if not conv_id:
            return
        state = self._get_state(conv_id)
        path = self._get_transcript_path(conv_id)
        if os.path.isfile(path):
            end_offset, highest_step = await asyncio.to_thread(self._scan_eof_state, path)
            state["offset"] = end_offset
            if highest_step > state["step_index"]:
                state["step_index"] = highest_step
        state["bullets"] = []
        state["initialized"] = True

    @staticmethod
    def _scan_eof_state(path: str) -> Tuple[int, int]:
        highest_step = -1
        offset = 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        step = d.get("step_index", -1)
                        if isinstance(step, int) and step > highest_step:
                            highest_step = step
                    except Exception:
                        pass
                offset = f.tell()
        except Exception:
            try:
                offset = os.path.getsize(path)
            except OSError:
                offset = 0
        return offset, highest_step

    @staticmethod
    def _scan_initial_state(path: str) -> Tuple[int, int, Optional[int]]:
        """Scans transcript on first attach to resume an active turn or start at EOF."""
        last_user_offset = 0
        last_user_step = -1
        has_completed_model = False
        highest_step = -1
        eof_offset = 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            while True:
                line_offset = f.tell()
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    step = d.get("step_index", -1)
                    if isinstance(step, int) and step > highest_step:
                        highest_step = step
                    src = d.get("source")
                    rec_type = d.get("type")
                    content = d.get("content")
                    if src == "USER_EXPLICIT" and rec_type == "USER_INPUT":
                        last_user_offset = line_offset
                        last_user_step = step
                        has_completed_model = False
                    elif src == "MODEL" and rec_type == "PLANNER_RESPONSE":
                        if content and content.strip():
                            has_completed_model = True
                except Exception:
                    pass
            eof_offset = f.tell()

        if last_user_step != -1 and not has_completed_model:
            return last_user_offset, last_user_step - 1, last_user_step
        return eof_offset, highest_step, None

    @staticmethod
    def _read_new_lines(path: str, last_offset: int) -> Tuple[List[str], int]:
        """Reads newly flushed complete lines from transcript.jsonl without blocking the event loop."""
        if not os.path.isfile(path):
            return [], last_offset

        current_size = os.path.getsize(path)
        if current_size < last_offset:
            last_offset = 0

        if current_size <= last_offset:
            return [], last_offset

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_offset)
            new_lines = f.readlines()
            if new_lines and not new_lines[-1].endswith("\n"):
                incomplete = new_lines.pop()
                new_offset = f.tell() - len(incomplete.encode("utf-8", errors="replace"))
            else:
                new_offset = f.tell()
        return new_lines, new_offset

    async def _init_tracking_for_conv(self, conv_id: str):
        self._current_conv_id = conv_id
        state = self._get_state(conv_id)
        path = self._get_transcript_path(conv_id)
        state["offset"] = 0
        state["step_index"] = -1
        state["bullets"] = []
        state["initialized"] = True

        if os.path.isfile(path):
            try:
                offset, step_idx, rewound_step = await asyncio.to_thread(self._scan_initial_state, path)
                state["offset"] = offset
                state["step_index"] = step_idx
                if rewound_step is not None:
                    logger.info(
                        f"Initialized watcher on active turn in session {conv_id} (rewound to step {rewound_step})"
                    )
                else:
                    logger.info(f"Initialized watcher on idle session {conv_id} at step {step_idx}")
            except Exception as e:
                logger.warning(f"Error initializing transcript tracking: {e}")

    async def _watch_loop(self):
        while self._running:
            try:
                if not self.is_enabled:
                    await asyncio.sleep(1.0)
                    continue

                conv_id = await asyncio.to_thread(self.get_active_conv_id)
                if not conv_id:
                    await asyncio.sleep(1.0)
                    continue

                state = self._get_state(conv_id)
                if not state["initialized"]:
                    await self._init_tracking_for_conv(conv_id)
                else:
                    self._current_conv_id = conv_id

                path = self._get_transcript_path(conv_id)
                if not os.path.isfile(path):
                    await asyncio.sleep(1.0)
                    continue

                prev_offset = state["offset"]
                new_lines, new_offset = await asyncio.to_thread(self._read_new_lines, path, prev_offset)
                if new_offset < prev_offset:
                    # File truncated/rotated
                    state["step_index"] = -1
                    state["bullets"] = []
                state["offset"] = new_offset

                for line in new_lines:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        step_index = record.get("step_index", -1)
                        if isinstance(step_index, int) and step_index <= state["step_index"]:
                            continue
                        if isinstance(step_index, int):
                            state["step_index"] = step_index

                        # Skip emitting callbacks if headless bot turn owns this execution
                        if self.is_bot_running():
                            continue

                        source = record.get("source")
                        rec_type = record.get("type")
                        content = record.get("content", "")

                        if source == "USER_EXPLICIT" and rec_type == "USER_INPUT":
                            state["bullets"] = []
                            clean_prompt = extract_clean_user_content(content)
                            if clean_prompt:
                                await self.on_user_turn(conv_id, clean_prompt)

                        elif source == "MODEL" and rec_type == "PLANNER_RESPONSE":
                            thinking = record.get("thinking", "")
                            th_bullet = format_thinking(thinking)
                            if th_bullet:
                                state["bullets"].append(th_bullet)
                                if self.on_activity_step:
                                    await self.on_activity_step(conv_id, th_bullet)

                            tool_calls = record.get("tool_calls", [])
                            for tc in tool_calls:
                                tc_bullet = format_tool_call(tc)
                                state["bullets"].append(tc_bullet)
                                if self.on_activity_step:
                                    await self.on_activity_step(conv_id, tc_bullet)

                            if content and content.strip():
                                await self.on_model_turn(
                                    conv_id,
                                    content.strip(),
                                    list(state["bullets"]),
                                )
                                state["bullets"] = []

                    except Exception as parse_err:
                        logger.debug(f"Failed to parse transcript line: {parse_err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in transcript watcher loop: {e}", exc_info=True)

            await asyncio.sleep(1.0)
