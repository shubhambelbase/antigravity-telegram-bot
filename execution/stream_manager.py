"""Hybrid Message Editing + Event-Based Streaming Manager for Telegram.

Implements a remote terminal experience in Telegram without chat flooding:
1. Persistent Telegram message: sent once when a session starts.
2. Continuous buffer: captures stdout/stderr and tool execution logs.
3. 500ms accumulation debounce: prevents API flooding on line bursts.
4. ~1.0s periodic edit: updates the persistent message via editMessageText.
5. Event-based notifications: sends distinct separate messages for task completion,
   errors, or cancellation with retry and safe HTML fallback.
"""

import asyncio
import html
import io
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

from execution.formatter import sanitize_secrets
from execution.progress_tracker import AdaptiveProgressTracker

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
KNOWN_HTML_TAGS_RE = re.compile(r"</?(?:code|b|strong|em|pre|a|i|blockquote|u|s)\b[^>]*>")
SAFE_TELEGRAM_LIMIT = 3900

T = TypeVar("T")


def strip_ansi(text: str) -> str:
    """Removes ANSI color and control escape sequences."""
    return ANSI_ESCAPE_RE.sub("", text)


def html_to_plain_text(text: str) -> str:
    """Converts Telegram HTML markup back to readable plain text without destroying code syntax like <int>."""
    if not text:
        return ""
    return html.unescape(KNOWN_HTML_TAGS_RE.sub("", text))


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
    clean = sanitize_secrets(clean)
    clean = KNOWN_HTML_TAGS_RE.sub("", clean)
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


async def call_with_retry(
    op: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Retries transient Telegram network/timeout/rate-limit errors; raises permanent errors immediately."""
    last_err: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await op()
        except Exception as e:
            last_err = e
            err_lower = str(e).lower()
            if any(perm in err_lower for perm in ("can't parse entities", "message is too long", "bad request", "chat not found", "blocked")):
                raise

            retry_match = re.search(r"retry\s+(?:after|in)\s+(\d+)", err_lower)
            if retry_match:
                delay = min(15.0, float(int(retry_match.group(1))) + 0.5)
            elif attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
            else:
                raise
            logger.debug(f"Telegram API call failed (attempt {attempt}/{attempts}): {e}; retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
    assert last_err is not None
    raise last_err


class HybridStreamSession:
    """Manages a single persistent terminal message with buffered streaming and event alerts."""

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        title: str = "Antigravity Session",
        edit_interval: float = 1.0,
        buffer_debounce: float = 0.5,
        skeleton_timeout: float = 45.0,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.title = title
        self.edit_interval = edit_interval
        self.buffer_debounce = buffer_debounce
        self.skeleton_timeout = skeleton_timeout
        self.progress = AdaptiveProgressTracker(operation_title=title)

        self.message_id: Optional[int] = None
        self._buffer: List[str] = []
        self._skeleton_step: int = 0
        self.has_real_output: bool = False
        self.header_info: Optional[str] = None
        self._start_time: float = time.time()
        self._skeleton_paused: bool = False
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
        if len(self._buffer) > 5000:
            self._buffer = self._buffer[-4000:]
        self._last_received_time = time.time()
        for line in chunk.splitlines():
            sline = line.strip()
            if sline:
                self.progress.feed_line(line)
                if not self.has_real_output:
                    if not any(ign in sline.lower() for ign in ["waiting for live", "injecting prompt"]):
                        self.has_real_output = True
                        self._skeleton_paused = False

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

    def _build_header_block(self, max_header_chars: int = 900) -> str:
        if not self.header_info:
            return ""
        raw = self.header_info
        if len(raw) <= max_header_chars:
            return f"<blockquote>{raw}</blockquote>\n\n"
        # Fall back to safe plain text truncation if header_info contains an oversized prompt
        plain = html_to_plain_text(raw)
        if len(plain) > max_header_chars - 30:
            plain = plain[: max_header_chars - 33] + "..."
        return f"<blockquote>{html.escape(plain)}</blockquote>\n\n"

    def _render_current_view(self, status: Optional[str] = None) -> str:
        current_status = status or self._status
        dashboard = self.progress.render_dashboard(status=current_status)
        header_block = self._build_header_block(max_header_chars=900)

        wrapper_prefix = f"{dashboard}\n\n{header_block}<pre><code class=\"language-bash\">"
        wrapper_suffix = "</code></pre>"
        available_for_code = max(250, SAFE_TELEGRAM_LIMIT - len(wrapper_prefix) - len(wrapper_suffix))

        if self.has_real_output:
            raw_text = self.get_full_buffer_text()
            terminal_view = format_terminal_window(raw_text, max_chars=min(2800, available_for_code))
            if terminal_view.strip():
                escaped_code = html.escape(terminal_view)
                # Shrink from top if HTML entity expansion (<, >, &) exceeded budget
                while len(escaped_code) > available_for_code and len(terminal_view) > 80:
                    overflow = len(escaped_code) - available_for_code
                    cut = max(40, overflow // 2 + 25)
                    trimmed = terminal_view[cut:]
                    nl = trimmed.find("\n")
                    if nl != -1 and nl < 120:
                        trimmed = trimmed[nl + 1 :]
                    terminal_view = f"... [truncated] ...\n{trimmed}"
                    escaped_code = html.escape(terminal_view)
                if len(escaped_code) > available_for_code:
                    escaped_code = html.escape(terminal_view[-(available_for_code // 2) :])
                return f"{wrapper_prefix}{escaped_code}{wrapper_suffix}"

        skeleton = self._render_skeleton_terminal()
        escaped_skeleton = html.escape(skeleton)
        return f"{wrapper_prefix}{escaped_skeleton}{wrapper_suffix}"

    async def start(self, initial_status: str = "Initializing...", initial_prompt: Optional[str] = None) -> Optional[int]:
        """Lifecycle Step 1: Send initial persistent message and start 1s flush loop."""
        self._status = initial_status
        self._is_active = True
        now = time.time()
        self._start_time = now
        self._skeleton_paused = False
        self._last_received_time = now
        self._last_edit_time = now

        if initial_prompt:
            self.progress.operation_title = initial_prompt

        initial_text = self._render_current_view(status=initial_status)

        try:
            sent = await call_with_retry(
                lambda: self.bot.send_message(
                    chat_id=self.chat_id,
                    text=initial_text,
                    parse_mode="HTML",
                )
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

                # Animate skeleton loader while waiting for real output, with bounded idle timeout
                if not self.has_real_output:
                    if self._skeleton_paused:
                        continue
                    if self.skeleton_timeout > 0 and (now - self._start_time) >= self.skeleton_timeout:
                        self._skeleton_paused = True
                        await self._edit_live_message(status="Waiting for terminal...")
                        continue
                    if now - self._last_edit_time >= max(1.0, self.edit_interval):
                        await self._edit_live_message()
                    continue

                if now - self._last_edit_time < self.edit_interval:
                    continue

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
        """Updates the persistent message text via editMessageText with rate-limit and length resilience."""
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
                    m = re.search(r"retry\s+after\s+(\d+)", err_str)
                    backoff = float(int(m.group(1))) if m else 2.0
                    self._last_edit_time = time.time() + max(2.0, backoff)
                elif "can't parse entities" in err_str or "message is too long" in err_str:
                    logger.warning(f"Stream edit HTML/length issue ({e}); retrying plain text.")
                    plain_rendered = html_to_plain_text(rendered)[:SAFE_TELEGRAM_LIMIT]
                    try:
                        await self.bot.edit_message_text(
                            chat_id=self.chat_id,
                            message_id=self.message_id,
                            text=plain_rendered,
                            parse_mode=None,
                        )
                        self._last_rendered_text = rendered
                        self._last_edit_time = time.time()
                    except Exception as fallback_err:
                        logger.debug(f"Fallback plain edit failed: {fallback_err}")
                else:
                    logger.debug(f"Failed to edit stream message: {e}")

    async def _send_html_or_plain(self, html_text: str) -> None:
        """Sends an HTML message with retry and safe plain-text entity-unescaped fallback."""
        try:
            await call_with_retry(
                lambda: self.bot.send_message(
                    chat_id=self.chat_id,
                    text=html_text,
                    parse_mode="HTML",
                )
            )
        except Exception as html_err:
            err_lower = str(html_err).lower()
            if "can't parse entities" in err_lower or "message is too long" in err_lower or "bad request" in err_lower:
                logger.warning(f"HTML send failed ({html_err}), retrying plain-text")
                plain_body = html_to_plain_text(html_text)[:SAFE_TELEGRAM_LIMIT]
                await call_with_retry(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=plain_body or html_text[:SAFE_TELEGRAM_LIMIT],
                        parse_mode=None,
                    )
                )
            else:
                raise

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

        if event_notification:
            try:
                plain_len = len(html_to_plain_text(event_notification))
                if len(event_notification) <= SAFE_TELEGRAM_LIMIT and plain_len <= SAFE_TELEGRAM_LIMIT:
                    await self._send_html_or_plain(event_notification)
                else:
                    summary_header = "✅ <b>Task Completed</b>\n<i>Output exceeds message length limit, attached below:</i>"
                    await self._send_html_or_plain(summary_header)
                    content_to_attach = full_output or html_to_plain_text(event_notification)
                    raw_bytes = content_to_attach.encode("utf-8")

                    async def _send_doc():
                        doc_bytes = io.BytesIO(raw_bytes)
                        doc_bytes.name = "antigravity_output.txt"
                        return await self.bot.send_document(
                            chat_id=self.chat_id,
                            document=doc_bytes,
                            caption="📄 Full execution output log",
                        )

                    await call_with_retry(_send_doc)
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

        safe_err = sanitize_secrets(error_message)[:3500]
        error_event = (
            f"❌ <b>Execution Error Occurred:</b>\n\n"
            f"<code>{html.escape(safe_err)}</code>"
        )
        try:
            await self._send_html_or_plain(error_event)
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
            await self._send_html_or_plain(
                "🛑 <b>Task Cancelled.</b>\n<i>Execution terminated by user request.</i>"
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
        skeleton_timeout: float = 45.0,
    ) -> HybridStreamSession:
        prev = self._sessions.get(chat_id)
        if prev and prev.is_active:
            await prev.complete(final_status="Superseded")

        session = HybridStreamSession(
            bot=self.bot,
            chat_id=chat_id,
            title=title,
            edit_interval=edit_interval,
            buffer_debounce=buffer_debounce,
            skeleton_timeout=skeleton_timeout,
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
