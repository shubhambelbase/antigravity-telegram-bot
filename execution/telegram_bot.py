"""Autonomous Antigravity Telegram Bot Controller.

Listens for Telegram commands, handles inline session-switching buttons,
directly types into the open desktop PC terminal screen in real-time,
mirrors live PC terminal interactions and tool logs (Thought/Ran/Edited) to Telegram,
and streams progress back with native Markdown rendering and Human-in-the-Loop pairing security.
"""

import atexit
import asyncio
import html
import io
import logging
import os
import time
from typing import Dict, List, Set

import psutil
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from execution.agy_runner import AntigravityRunner, ConversationInfo
from execution.console_injector import find_interactive_agy_pid, inject_text_to_agy
from execution.formatter import markdown_to_telegram_html
from execution.transcript_watcher import TranscriptWatcher

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Load environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
PID_FILE = os.path.join(BASE_DIR, ".bot.pid")
load_dotenv(DOTENV_PATH)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_WORKSPACE = os.getenv("DEFAULT_WORKSPACE", os.getcwd())
AGY_PATH = os.getenv("AGY_PATH")


def parse_allowed_ids() -> Set[int]:
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if not raw:
        return set()
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ALLOWED_USER_IDS = parse_allowed_ids()
runner = AntigravityRunner(agy_path=AGY_PATH, default_workspace=DEFAULT_WORKSPACE)


def save_claimed_user(user_id: int):
    global ALLOWED_USER_IDS
    ALLOWED_USER_IDS.add(user_id)
    lines = []
    found = False
    if os.path.exists(DOTENV_PATH):
        with open(DOTENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.startswith("ALLOWED_TELEGRAM_USER_IDS="):
            new_lines.append(f"ALLOWED_TELEGRAM_USER_IDS={user_id}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"ALLOWED_TELEGRAM_USER_IDS={user_id}\n")

    with open(DOTENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    logger.info(f"Saved ALLOWED_TELEGRAM_USER_IDS={user_id} to {DOTENV_PATH}")


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return False
    return user_id in ALLOWED_USER_IDS


async def check_auth(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False

    if not ALLOWED_USER_IDS:
        await update.message.reply_text(
            f"🔒 <b>Antigravity Controller (Setup Mode)</b>\n\n"
            f"Your Telegram User ID is: <code>{user.id}</code>\n\n"
            f"This bot is currently unclaimed. To pair and lock it to your account, send:\n"
            f"<code>/claim {user.id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return False

    if user.id not in ALLOWED_USER_IDS:
        if update.message:
            await update.message.reply_text(
                f"⛔ <b>Access Denied</b>\n"
                f"Your Telegram User ID (<code>{user.id}</code>) is not authorized to control this machine.",
                parse_mode=ParseMode.HTML,
            )
        logger.warning(f"Unauthorized access attempt by user {user.id} ({user.username})")
        return False

    return True


# Command Handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if not ALLOWED_USER_IDS or not is_authorized(user.id):
        await check_auth(update)
        return

    interactive_pid = find_interactive_agy_pid()
    screen_status = f"🟢 Connected (PID {interactive_pid})" if interactive_pid else "⚪ Headless (No desktop terminal)"
    conv_text = f"<code>{runner.conversation_id}</code>" if runner.conversation_id else "Auto-Tracking"

    welcome_text = (
        f"🤖 <b>Antigravity Controller Online</b>\n\n"
        f"<b>PC Screen Control:</b> {screen_status}\n"
        f"<b>Workspace:</b> <code>{html.escape(runner.workspace_dir)}</code>\n"
        f"<b>Session:</b> {conv_text}\n"
        f"<b>Features:</b> Live Screen Typing + Tool Logs (Thought/Ran/Edited)\n\n"
        f"<b>Quick Actions:</b>\n"
        f"• Send any prompt to type & run directly on your PC screen\n"
        f"• /sessions - View recent sessions with 1-click attach buttons\n"
        f"• /status - Check host, active session, and agent state\n"
        f"• /cd &lt;path&gt; - Switch active workspace directory\n"
        f"• /pwd - Show current working directory\n"
        f"• /new - Start fresh conversation session\n"
        f"• /stop - Immediately kill running task\n"
        f"• /help - View command details"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if ALLOWED_USER_IDS:
        await update.message.reply_text(
            "🔒 Bot is already claimed and locked down.",
            parse_mode=ParseMode.HTML,
        )
        return

    args = context.args
    if not args or args[0] != str(user.id):
        await update.message.reply_text(
            f"To claim, send: <code>/claim {user.id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    save_claimed_user(user.id)
    await update.message.reply_text(
        f"✅ <b>Successfully Paired!</b>\n"
        f"Bot is now strictly locked to your User ID (<code>{user.id}</code>).\n\n"
        f"You can now send any coding prompt or command.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    recents = runner.get_recent_conversations(limit=5)
    if not recents:
        await update.message.reply_text("ℹ️ No previous conversation sessions found.")
        return

    lines = ["📜 <b>Recent Antigravity Sessions:</b>\n"]
    keyboard = []

    for idx, s in enumerate(recents, 1):
        is_active = " <b>[ACTIVE]</b>" if runner.conversation_id == s.conv_id else ""
        lines.append(
            f"<b>{idx}.</b> <code>{s.conv_id[:8]}...</code> ({s.updated_at}){is_active}\n"
            f"   <i>\"{html.escape(s.preview)}\"</i>\n"
        )
        btn_label = f"Attach #{idx} ({s.conv_id[:8]})"
        if runner.conversation_id == s.conv_id:
            btn_label = f"✅ Active #{idx} ({s.conv_id[:8]})"
        keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"attach:{s.conv_id}")])

    lines.append("<i>Tap an inline button below to attach to that session with full history:</i>")
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()
    user = update.effective_user
    if not user or not is_authorized(user.id):
        return

    data = query.data or ""
    if data.startswith("attach:"):
        conv_id = data.split("attach:", 1)[1]
        if runner.set_conversation(conv_id):
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"🔗 <b>Attached to Session:</b> <code>{html.escape(conv_id)}</code>\n\n"
                f"Your future messages and live PC terminal activity are now synchronized with this conversation!",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.message.reply_text(f"❌ Failed to attach to session: <code>{html.escape(conv_id)}</code>", parse_mode=ParseMode.HTML)


async def cmd_attach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/attach &lt;number (1-5) or conversation ID&gt;</code>\n"
            "Run /sessions first to view available sessions.",
            parse_mode=ParseMode.HTML,
        )
        return

    target = context.args[0].strip()
    recents = runner.get_recent_conversations(limit=10)

    chosen_id = None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(recents):
            chosen_id = recents[idx - 1].conv_id
        else:
            await update.message.reply_text(f"❌ Invalid session number. Choose between 1 and {len(recents)}.")
            return
    else:
        chosen_id = target

    if runner.set_conversation(chosen_id):
        await update.message.reply_text(
            f"🔗 <b>Attached to Conversation Session:</b>\n"
            f"<code>{html.escape(runner.conversation_id)}</code>\n\n"
            f"All your future prompts and live PC terminal activity will now synchronize with this session!",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ Could not find session: <code>{html.escape(chosen_id)}</code>\n"
            f"Run /sessions to view valid sessions.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    cpu_pct = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    agent_state = "🟡 Running" if runner.is_running else "🟢 Idle"
    conv_text = f"<code>{runner.conversation_id}</code>" if runner.conversation_id else "Auto-Continuous"
    interactive_pid = find_interactive_agy_pid()
    screen_status = f"🟢 Connected (PID {interactive_pid})" if interactive_pid else "⚪ Headless (No active terminal)"

    status_msg = (
        f"📊 <b>System & Agent Status</b>\n\n"
        f"<b>PC Screen Control:</b> {screen_status}\n"
        f"<b>Agent Status:</b> {agent_state}\n"
        f"<b>Workspace:</b> <code>{html.escape(runner.workspace_dir)}</code>\n"
        f"<b>Active Session:</b> {conv_text}\n"
        f"<b>Live Tool Logs:</b> 🟢 Active\n"
        f"<b>Host CPU:</b> {cpu_pct}%\n"
        f"<b>Host RAM:</b> {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)"
    )
    await update.message.reply_text(status_msg, parse_mode=ParseMode.HTML)


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: <code>/cd &lt;path&gt;</code>", parse_mode=ParseMode.HTML)
        return

    target_path = " ".join(context.args).strip('"').strip("'")
    if runner.set_workspace(target_path):
        await update.message.reply_text(
            f"📁 Workspace switched to:\n<code>{html.escape(runner.workspace_dir)}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ Directory not found:\n<code>{html.escape(target_path)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    await update.message.reply_text(
        f"📁 Current Workspace:\n<code>{html.escape(runner.workspace_dir)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    runner.reset_conversation()
    await update.message.reply_text(
        "🔄 <b>Conversation session reset.</b>\nNext prompt will start a clean turn.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    if not runner.is_running:
        await update.message.reply_text("ℹ️ No active Antigravity task is currently running.")
        return

    killed = await runner.cancel()
    if killed:
        await update.message.reply_text("🛑 <b>Active task killed successfully.</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("⚠️ Could not kill process (it may have already completed).")


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    user_prompt = update.message.text.strip()
    if not user_prompt:
        return

    cleaned_input = user_prompt.lower().replace("...", "").strip()
    if cleaned_input.startswith("attach "):
        target_arg = user_prompt.split("attach ", 1)[1].strip()
        context.args = [target_arg]
        await cmd_attach(update, context)
        return

    if len(cleaned_input) >= 6 and not " " in cleaned_input:
        matched = [
            s for s in runner.get_recent_conversations(limit=10)
            if s.conv_id.startswith(cleaned_input) or s.conv_id.lower().startswith(cleaned_input)
        ]
        if len(matched) == 1:
            conv_id = matched[0].conv_id
            if runner.set_conversation(conv_id):
                await update.message.reply_text(
                    f"🔗 <b>Auto-Attached to Session:</b>\n<code>{html.escape(conv_id)}</code>\n\n"
                    f"<i>Topic: \"{html.escape(matched[0].preview)}\"</i>\n\n"
                    f"You are now continuing this conversation with full history!",
                    parse_mode=ParseMode.HTML,
                )
                return

    # Check if an interactive terminal window is open on the desktop
    interactive_pid = find_interactive_agy_pid()
    if interactive_pid:
        status_message = await update.message.reply_text(
            f"⚡ <b>Typing into PC Terminal Screen...</b>\n\n<code>{html.escape(user_prompt)}</code>",
            parse_mode=ParseMode.HTML,
        )
        injected = inject_text_to_agy(user_prompt, pid=interactive_pid)
        if injected:
            await status_message.edit_text(
                f"📺 <b>Prompt Injected & Running on PC Screen!</b>\n\n"
                f"<code>{html.escape(user_prompt)}</code>\n\n"
                f"<i>Your PC terminal is now executing this task live. Tool actions and results will stream here as they happen.</i>",
                parse_mode=ParseMode.HTML,
            )
            return

    # Fallback to headless execution if no interactive desktop terminal is running
    if runner.is_running:
        await update.message.reply_text(
            "⚠️ An Antigravity task is already executing. Send /stop to cancel it first.",
            parse_mode=ParseMode.HTML,
        )
        return

    session_hint = f" (Session: <code>{runner.conversation_id[:8]}...</code>)" if runner.conversation_id else ""
    status_message = await update.message.reply_text(
        f"⚡ <b>Antigravity Task Started...{session_hint}</b>\n<i>Initializing agent environment...</i>",
        parse_mode=ParseMode.HTML,
    )

    last_edit_time = 0.0
    buffer_lines = []

    async def on_stream_chunk(line: str):
        nonlocal last_edit_time
        buffer_lines.append(line)
        now = time.time()
        if now - last_edit_time > 2.0:
            last_edit_time = now
            tail = "".join(buffer_lines[-10:])
            escaped_tail = html.escape(tail)
            if len(escaped_tail) > 3000:
                escaped_tail = escaped_tail[-3000:]
            try:
                await status_message.edit_text(
                    f"⚡ <b>Antigravity Running...{session_hint}</b>\n\n<pre><code>{escaped_tail}</code></pre>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    result = await runner.execute_prompt(user_prompt, on_chunk=on_stream_chunk)

    if result.is_cancelled:
        await status_message.edit_text("🛑 <b>Task Cancelled.</b>", parse_mode=ParseMode.HTML)
        return

    if result.error_message:
        await status_message.edit_text(
            f"❌ <b>Error:</b>\n<code>{html.escape(result.error_message)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    final_text = result.full_output.strip() or "(Task completed with empty output)"
    conv_footer = f"\n\n<i>Session: <code>{runner.conversation_id}</code></i>" if runner.conversation_id else ""
    formatted_html = markdown_to_telegram_html(final_text)

    if len(formatted_html) + len(conv_footer) <= 3800:
        try:
            await status_message.edit_text(
                f"✅ <b>Task Complete:</b>\n\n{formatted_html}{conv_footer}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await status_message.edit_text(
                f"✅ <b>Task Complete:</b>\n\n<pre><code>{html.escape(final_text)}</code></pre>{conv_footer}",
                parse_mode=ParseMode.HTML,
            )
    else:
        await status_message.edit_text(f"✅ <b>Task Complete:</b> (Output attached below){conv_footer}", parse_mode=ParseMode.HTML)
        doc = io.BytesIO(final_text.encode("utf-8"))
        doc.name = "antigravity_output.txt"
        await update.message.reply_document(
            document=doc,
            caption="📄 Full execution output log",
        )


def check_single_instance() -> bool:
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                proc = psutil.Process(old_pid)
                if "python" in proc.name().lower():
                    logger.warning(f"Another instance is already running with PID {old_pid}. Exiting.")
                    return False
        except Exception:
            pass

    current_pid = os.getpid()
    with open(PID_FILE, "w") as f:
        f.write(str(current_pid))

    def cleanup():
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass

    atexit.register(cleanup)
    return True


async def post_init(application: Application):
    """Initializes and starts the real-time transcript mirror watcher with throttled live tool logs."""
    live_progress_msgs: Dict[int, int] = {}
    live_bullets_buffer: Dict[int, List[str]] = {}
    last_step_edit_time: Dict[int, float] = {}

    async def on_pc_user(conv_id: str, prompt: str):
        live_bullets_buffer.clear()
        for user_id in ALLOWED_USER_IDS:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"💻 <b>[PC Terminal User Input]</b>\n\n<code>{html.escape(prompt)}</code>",
                    parse_mode=ParseMode.HTML,
                )
                live_progress_msgs.pop(user_id, None)
            except Exception as e:
                logger.warning(f"Failed to mirror PC prompt: {e}")

    async def on_pc_activity_step(conv_id: str, bullet: str):
        """Streams live tool execution and thought bullets to Telegram with rate-limiting."""
        now = time.time()
        for user_id in ALLOWED_USER_IDS:
            bullets = live_bullets_buffer.setdefault(user_id, [])
            bullets.append(bullet)
            recent_bullets = bullets[-6:]  # Keep last 6 actions visible
            display_text = "⚡ <b>Antigravity Working...</b>\n\n" + "\n".join(recent_bullets)

            # Throttle edits to at most once per 1.5s to prevent rate limits
            if user_id in live_progress_msgs and (now - last_step_edit_time.get(user_id, 0.0) < 1.5):
                continue
            last_step_edit_time[user_id] = now

            try:
                msg_id = live_progress_msgs.get(user_id)
                if not msg_id:
                    sent = await application.bot.send_message(
                        chat_id=user_id,
                        text=display_text,
                        parse_mode=ParseMode.HTML,
                    )
                    live_progress_msgs[user_id] = sent.message_id
                else:
                    await application.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg_id,
                        text=display_text,
                        parse_mode=ParseMode.HTML,
                    )
            except Exception:
                pass

    async def on_pc_model(conv_id: str, content: str, all_bullets: List[str]):
        formatted_html = markdown_to_telegram_html(content)
        steps_summary = ""
        if all_bullets:
            steps_joined = "\n".join(all_bullets[-8:])
            steps_summary = f"📋 <b>Execution Log:</b>\n<blockquote>{steps_joined}</blockquote>\n\n"

        full_message = f"{steps_summary}🤖 <b>[Antigravity Response]</b>\n\n{formatted_html}"

        for user_id in ALLOWED_USER_IDS:
            live_progress_msgs.pop(user_id, None)
            live_bullets_buffer.pop(user_id, None)

            try:
                if len(full_message) <= 3800:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=full_message,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    doc = io.BytesIO(content.encode("utf-8"))
                    doc.name = "antigravity_pc_output.txt"
                    header = steps_summary if steps_summary else "🤖 <b>[Antigravity Response]</b>\n\n"
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=header + "<i>(Full output attached below due to length)</i>",
                        parse_mode=ParseMode.HTML,
                    )
                    await application.bot.send_document(
                        chat_id=user_id,
                        document=doc,
                        caption="📄 Antigravity Output",
                    )
            except Exception as e:
                logger.warning(f"Failed to mirror PC response: {e}")

    watcher = TranscriptWatcher(
        brain_dir=runner.brain_dir,
        get_active_conv_id=lambda: runner.conversation_id,
        is_bot_running=lambda: runner.is_running,
        on_user_turn=on_pc_user,
        on_model_turn=on_pc_model,
        on_activity_step=on_pc_activity_step,
    )
    watcher.start()
    application.bot_data["watcher"] = watcher
    logger.info("Transcript live mirror watcher with tool logs active.")


async def post_shutdown(application: Application):
    watcher = application.bot_data.get("watcher")
    if watcher:
        watcher.stop()


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs unexpected exceptions cleanly without crashing."""
    logger.error("Unhandled exception occurred:", exc_info=context.error)


def main():
    if not check_single_instance():
        print("Bot is already running in another window/process.")
        return

    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing in .env")
        return

    logger.info("Starting Antigravity Telegram Bot with Live PC Console Injection & Tool Logs...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("claim", cmd_claim))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("attach", cmd_attach))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("cancel", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    app.add_error_handler(global_error_handler)

    logger.info("Bot is polling with live PC terminal injection and tool execution logs...")
    app.run_polling()


if __name__ == "__main__":
    main()
