"""Hybrid Message Editing + Event-Based Streaming Manager for Telegram.

Implements a remote terminal experience in Telegram without chat flooding:
1. Persistent Telegram message: sent once when a session starts.
2. Continuous buffer: captures stdout/stderr and tool execution logs.
3. 500ms accumulation debounce: prevents API flooding on line bursts.
4. ~1.0s periodic edit: updates the persistent message via editMessageText.
5. Event-based notifications: sends distinct separate messages for task completion,
   errors, or cancellation.
"""

import asyncio
import html
import io
import logging
import re
import time
from typing import Any, Dict, List, Optional

from execution.formatter import sanitize_secrets
from execution.progress_tracker import AdaptiveProgressTracker, ProgressMode

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Removes ANSI color and control escape sequences."""
    return ANSI_ESCAPE_RE.sub("", text)


def collapse_consecutive_lines(lines: List[str]) -> List[str]:
    """Collapses consecutive identical lines into a single line with count (e.g. line (x3))."""
    clean_lines = [l.strip() for l in lines if l and l.strip()]
    if not clean_lines:
        return []

    collapsed: List[str] = []
    current_line = clean_lines[0]
    count = 1

    for line in clean_lines[1:]:
        if line == current_line:
            count += 1
        else:
            collapsed.append(f"{current_line} (x{count})" if count > 1 else current_line)
            current_line = line
            count = 1

    collapsed.append(f"{current_line} (x{count})" if count > 1 else current_line)
    return collapsed


def format_terminal_window(raw: str, max_chars: int = 2800, max_lines: int = 8) -> str:
    """Formats output buffer into a compact, clean terminal view fitting Telegram limits.

    - Strips ANSI sequences and raw HTML tags.
    - Collapses consecutive duplicate actions (e.g. repeated file reads).
    - Limits visible window to the most recent max_lines with a clear folding badge.
    """
    clean = strip_ansi(raw).replace("\r\n", "\n").replace("\r", "\n")
    # Redact sensitive tokens and secrets from live output
    clean = sanitize_secrets(clean)
    # Strip HTML markup tags (e.g. <code>, </i>) without destroying code generics like vector<int> or redirects
    clean = re.sub(r"</?(?:code|b|strong|em|pre|a|i)\b[^>]*>", "", clean)
    # Unescape html entities so code block displays natural symbols
    clean = html.unescape(clean)

    raw_lines = clean.splitlines()
    collapsed = collapse_consecutive_lines(raw_lines)
    if not collapsed:
        return ""

    truncated_count = 0
    if len(collapsed) > max_lines:
        truncated_count = len(collapsed) - max_lines
        collapsed = collapsed[-max_lines:]

    result = "\n".join(collapsed)

    if len(result) > max_chars:
        result = result[-max_chars:]
        first_nl = result.find("\n")
        if first_nl != -1 and first_nl < 120:
            result = result[first_nl + 1 :]
        truncated_count = max(1, truncated_count)

    if truncated_count > 0:
        return f"... [earlier terminal output truncated] ... ({truncated_count} earlier steps)\n{result}"

    return result


class HybridStreamSession:
    """Manages a single persistent terminal message with buffered streaming and event alerts."""

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        title: str = "Antigravity Session",
        edit_interval: float = 1.0,
        buffer_debounce: float = 0.5,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.title = title
        self.edit_interval = edit_interval
        self.buffer_debounce = buffer_debounce
        self.progress = AdaptiveProgressTracker(operation_title=title)

        self.message_id: Optional[int] = None
        self._buffer: List[str] = []
        self._skeleton_step: int = 0
        self.has_real_output: bool = False
        self.header_info: Optional[str] = None
        self._last_received_time: float = 0.0
        self._last_edit_time: float = 0.0
        self._last_rendered_text: str = ""
        self._status: str = "Starting"
        self._is_active: bool = False
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        return self._is_active

    def set_header_info(self, text: str):
        """Sets informational header text (e.g. desktop prompt injection target) without marking has_real_output."""
        self.header_info = text

    def get_full_buffer_text(self) -> str:
        return "".join(self._buffer)

    def feed(self, chunk: str):
        """Buffers arriving chunk of terminal output or tool log and updates progress."""
        if not chunk:
            return
        self._buffer.append(chunk)
        # Cap buffer to 5,000 chunks to prevent memory exhaustion on runaway infinite loops
        if len(self._buffer) > 5000:
            self._buffer = self._buffer[-4000:]
        self._last_received_time = time.time()
        for line in chunk.splitlines():
            sline = line.strip()
            if sline:
                self.progress.feed_line(line)
                if not self.has_real_output:
                    # Ignore mere initial waiting status strings if any
                    if not any(ign in sline.lower() for ign in ["waiting for live", "injecting prompt"]):
                        self.has_real_output = True

    def _render_skeleton_terminal(self) -> str:
        """Renders an animated shimmering skeleton placeholder while waiting for terminal output."""
        def make_shimmer(step: int, width: int) -> str:
            chars = ["░"] * width
            wave = ["▒", "▓", "█", "▓", "▒"]
            pos = step % (width + len(wave)) - len(wave)
            for i, ch in enumerate(wave):
                idx = pos + i
                if 0 <= idx < width:
                    chars[idx] = ch
            return "".join(chars)

        step = self._skeleton_step
        self._skeleton_step += 1

        line1 = make_shimmer(step, 36)
        line2 = make_shimmer(step + 4, 26)
        line3 = make_shimmer(step + 8, 32)
        line4 = make_shimmer(step + 12, 20)

        return (
            "┌─ ⏳ Loading live terminal output stream... ────────────┐\n"
            f"│ {line1}\n"
            f"│ {line2}\n"
            f"│ {line3}\n"
            f"│ {line4}\n"
            "└────────────────────────────────────────────────────────┘"
        )

    def _render_current_view(self, status: Optional[str] = None) -> str:
        current_status = status or self._status
        dashboard = self.progress.render_dashboard(status=current_status)

        header_block = ""
        if self.header_info:
            header_block = f"<blockquote>{self.header_info}</blockquote>\n\n"

        if self.has_real_output:
            raw_text = self.get_full_buffer_text()
            terminal_view = format_terminal_window(raw_text, max_chars=2800)
            if terminal_view.strip():
                escaped_code = html.escape(terminal_view)
                return f"{dashboard}\n\n{header_block}<pre><code class=\"language-bash\">{escaped_code}</code></pre>"

        # In loading / initial phase before real output arrives: render animated skeleton terminal!
        skeleton = self._render_skeleton_terminal()
        escaped_skeleton = html.escape(skeleton)
        return f"{dashboard}\n\n{header_block}<pre><code class=\"language-bash\">{escaped_skeleton}</code></pre>"

    async def start(self, initial_status: str = "Initializing...", initial_prompt: Optional[str] = None) -> Optional[int]:
        """Lifecycle Step 1: Send initial persistent message and start 1s flush loop."""
        self._status = initial_status
        self._is_active = True
        self._last_received_time = time.time()
        self._last_edit_time = time.time()

        if initial_prompt:
            self.progress.operation_title = initial_prompt

        initial_text = self._render_current_view(status=initial_status)

        try:
            sent = await self.bot.send_message(
                chat_id=self.chat_id,
                text=initial_text,
                parse_mode="HTML",
            )
            self.message_id = sent.message_id
            self._last_rendered_text = initial_text
        except Exception as e:
            logger.error(f"Failed to send initial stream message to chat {self.chat_id}: {e}")
            self.message_id = None

        self._flush_task = asyncio.create_task(self._flush_loop())
        return self.message_id

    async def _flush_loop(self):
        """Lifecycle Steps 3 & 4: Accumulate 500ms and edit persistent message every ~1s."""
        while self._is_active:
            try:
                await asyncio.sleep(0.1)
                now = time.time()

                # Animate skeleton loader and spinner while loading (before real terminal output arrives)
                if not self.has_real_output:
                    if now - self._last_edit_time >= 1.0:
                        await self._edit_live_message()
                    continue

                # Check if edit interval (1.0s) has elapsed
                if now - self._last_edit_time < self.edit_interval:
                    continue

                # Check if buffer has received data and accumulated for debounce time (500ms),
                # or if data has been waiting for more than 1.5s to avoid starvation on streaming
                time_since_last_input = now - self._last_received_time
                has_accumulated = time_since_last_input >= self.buffer_debounce
                is_starving = (now - self._last_edit_time) >= 1.5

                if has_accumulated or is_starving:
                    await self._edit_live_message()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in stream flush loop: {e}")

    async def _edit_live_message(self, status: Optional[str] = None):
        """Updates the persistent message text via editMessageText."""
        if not self.message_id:
            return

        rendered = self._render_current_view(status=status)
        if rendered == self._last_rendered_text:
            return

        async with self._lock:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    text=rendered,
                    parse_mode="HTML",
                )
                self._last_rendered_text = rendered
                self._last_edit_time = time.time()
            except Exception as e:
                err_str = str(e).lower()
                if "message is not modified" in err_str:
                    self._last_rendered_text = rendered
                elif "retry after" in err_str:
                    logger.warning(f"Telegram rate-limited stream edit: {e}")
                    # Throttle by backing off
                    self._last_edit_time = time.time() + 2.0
                else:
                    logger.debug(f"Failed to edit stream message: {e}")

    async def complete(
        self,
        final_status: str = "Completed",
        event_notification: Optional[str] = None,
        full_output: Optional[str] = None,
    ):
        """Lifecycle Step 5: Update live message with final status and send separate event notification."""
        self._is_active = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

        self._status = final_status
        self.progress.complete()
        await self._edit_live_message(status=final_status)

        # Send separate completion event notification if provided
        if event_notification:
            try:
                if len(event_notification) <= 3900:
                    try:
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=event_notification,
                            parse_mode="HTML",
                        )
                    except Exception as html_err:
                        logger.warning(f"HTML send failed in complete(), retrying plain-text: {html_err}")
                        plain_body = re.sub(r"<[^>]+>", "", event_notification)
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=plain_body or event_notification,
                            parse_mode=None,
                        )
                else:
                    # If formatted notification exceeds 3900 chars, send summary and attach text document
                    summary_header = "✅ <b>Task Completed</b>\n<i>Output exceeds message length limit, attached below:</i>"
                    try:
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=summary_header,
                            parse_mode="HTML",
                        )
                    except Exception:
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text="✅ Task Completed\nOutput exceeds message length limit, attached below:",
                            parse_mode=None,
                        )
                    content_to_attach = full_output or event_notification
                    doc_bytes = io.BytesIO(content_to_attach.encode("utf-8"))
                    doc_bytes.name = "antigravity_output.txt"
                    await self.bot.send_document(
                        chat_id=self.chat_id,
                        document=doc_bytes,
                        caption="📄 Full execution output log",
                    )
            except Exception as e:
                logger.error(f"Failed to send completion event notification: {e}")

    async def fail(self, error_message: str):
        """Important Event: Updates live message to Failed and sends separate error notification."""
        self._is_active = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

        self._status = "Failed"
        self.progress.record_fixing(error_message[:40])
        await self._edit_live_message(status="Failed")

        error_event = (
            f"❌ <b>Execution Error Occurred:</b>\n\n"
            f"<code>{html.escape(error_message)}</code>"
        )
        try:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=error_event,
                    parse_mode="HTML",
                )
            except Exception as html_err:
                logger.warning(f"HTML send failed in fail(), retrying plain-text: {html_err}")
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"❌ Execution Error Occurred:\n\n{error_message}",
                    parse_mode=None,
                )
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")

    async def cancel(self):
        """Important Event: Updates live message to Cancelled and sends cancellation notification."""
        self._is_active = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

        self._status = "Cancelled"
        await self._edit_live_message(status="Cancelled")

        try:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text="🛑 <b>Task Cancelled.</b>\n<i>Execution terminated by user request.</i>",
                    parse_mode="HTML",
                )
            except Exception:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text="🛑 Task Cancelled.\nExecution terminated by user request.",
                    parse_mode=None,
                )
        except Exception as e:
            logger.error(f"Failed to send cancel notification: {e}")


class TerminalStreamManager:
    """Manages active hybrid stream sessions across chats."""

    def __init__(self, bot: Any):
        self.bot = bot
        self._sessions: Dict[int, HybridStreamSession] = {}

    def get_session(self, chat_id: int) -> Optional[HybridStreamSession]:
        return self._sessions.get(chat_id)

    async def start_session(
        self,
        chat_id: int,
        title: str = "Antigravity Session",
        initial_status: str = "Starting",
        initial_prompt: Optional[str] = None,
        edit_interval: float = 1.0,
        buffer_debounce: float = 0.5,
    ) -> HybridStreamSession:
        # Cancel any previous session in this chat
        prev = self._sessions.get(chat_id)
        if prev and prev.is_active:
            await prev.complete(final_status="Superseded")

        session = HybridStreamSession(
            bot=self.bot,
            chat_id=chat_id,
            title=title,
            edit_interval=edit_interval,
            buffer_debounce=buffer_debounce,
        )
        self._sessions[chat_id] = session
        await session.start(initial_status=initial_status, initial_prompt=initial_prompt)
        return session

    def feed(self, chat_id: int, chunk: str):
        session = self._sessions.get(chat_id)
        if session and session.is_active:
            session.feed(chunk)

    async def close_session(self, chat_id: int):
        session = self._sessions.pop(chat_id, None)
        if session and session.is_active:
            await session.complete(final_status="Closed")
