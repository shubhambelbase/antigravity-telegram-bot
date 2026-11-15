"""Autonomous Antigravity Telegram Bot Controller.

Listens for Telegram commands, handles inline session-switching buttons,
directly types into the open desktop PC terminal screen in real-time,
mirrors live PC terminal interactions and tool logs (Thought/Ran/Edited) to Telegram,
provides a persistent Quick-Action Keyboard (Bottom Bar) for 1-tap commands,
and streams progress back with a Hybrid Message Editing + Event-Based Streaming mechanism.
"""

import atexit
import asyncio
import html
import io
import logging
import os
import time
from typing import Dict, List, Optional, Set

import psutil
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
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
from execution.screenshot import get_screenshot
from execution.stream_manager import TerminalStreamManager
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

# Persistent Quick-Action Bottom Bar Keyboard
QUICK_ACTION_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 Status"), KeyboardButton("📜 Sessions"), KeyboardButton("📸 Screenshot")],
        [KeyboardButton("📁 PWD"), KeyboardButton("🔄 New Turn"), KeyboardButton("🛑 Stop Task")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


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
stream_manager: Optional[TerminalStreamManager] = None


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
        f"<b>Quick Keyboard:</b> Persistent Menu Active Below 👇\n\n"
        f"<b>Quick Actions:</b>\n"
        f"• Tap any button on the bottom bar for instant access\n"
        f"• Type any prompt to execute live on your PC screen\n"
        f"• /status - Check host health, active session, and CPU/RAM\n"
        f"• /sessions - View recent sessions with 1-click attach buttons\n"
        f"• /screenshot - Capture a live desktop or terminal snapshot\n"
        f"• /cd &lt;path&gt; - Switch active workspace directory\n"
        f"• /pwd - Show current working directory\n"
        f"• /new - Start fresh conversation session\n"
        f"• /stop - Immediately kill running task\n"
        f"• /help - View command details"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=QUICK_ACTION_KEYBOARD,
    )


async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if ALLOWED_USER_IDS:
        await update.message.reply_text(
            "🔒 Bot is already claimed and locked down.",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
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
        f"You can now send any coding prompt or tap buttons on the quick bar below.",
        parse_mode=ParseMode.HTML,
        reply_markup=QUICK_ACTION_KEYBOARD,
    )


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    recents = runner.get_recent_conversations(limit=5)
    if not recents:
        await update.message.reply_text(
            "ℹ️ No previous conversation sessions found.",
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
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
                reply_markup=QUICK_ACTION_KEYBOARD,
            )
        else:
            await query.message.reply_text(
                f"❌ Failed to attach to session: <code>{html.escape(conv_id)}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=QUICK_ACTION_KEYBOARD,
            )


async def cmd_attach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/attach &lt;number (1-5) or conversation ID&gt;</code>\n"
            "Run /sessions first to view available sessions.",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
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
            await update.message.reply_text(
                f"❌ Invalid session number. Choose between 1 and {len(recents)}.",
                reply_markup=QUICK_ACTION_KEYBOARD,
            )
            return
    else:
        chosen_id = target

    if runner.set_conversation(chosen_id):
        await update.message.reply_text(
            f"🔗 <b>Attached to Conversation Session:</b>\n"
            f"<code>{html.escape(runner.conversation_id)}</code>\n\n"
            f"All your future prompts and live PC terminal activity will now synchronize with this session!",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
    else:
        await update.message.reply_text(
            f"❌ Could not find session: <code>{html.escape(chosen_id)}</code>\n"
            f"Run /sessions to view valid sessions.",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
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
        f"<b>Streaming Engine:</b> 🟢 Hybrid Message Editing + Event Alerts\n"
        f"<b>Host CPU:</b> {cpu_pct}%\n"
        f"<b>Host RAM:</b> {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)"
    )
    await update.message.reply_text(
        status_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=QUICK_ACTION_KEYBOARD,
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    chat_id = update.effective_chat.id
    active_terminal_text = None
    if stream_manager:
        session = stream_manager.get_session(chat_id)
        if session:
            active_terminal_text = session.get_full_buffer_text()

    status_msg = await update.message.reply_text(
        "📸 <i>Capturing PC screen snapshot...</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        interactive_pid = find_interactive_agy_pid()
        title = f"Antigravity Terminal (PID {interactive_pid})" if interactive_pid else "Antigravity Console"
        png_bytes, caption = get_screenshot(fallback_terminal_text=active_terminal_text, title=title)

        photo_stream = io.BytesIO(png_bytes)
        photo_stream.name = "screenshot.png"

        await update.message.reply_photo(
            photo=photo_stream,
            caption=f"{caption}\n<i>Host: Windows | Screen Control: {'🟢 Connected' if interactive_pid else '⚪ Headless'}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Failed to capture screenshot: {e}")
        await status_msg.edit_text(
            f"❌ <b>Screenshot Error:</b> {html.escape(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/cd &lt;path&gt;</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    target_path = " ".join(context.args).strip('"').strip("'")
    if runner.set_workspace(target_path):
        await update.message.reply_text(
            f"📁 Workspace switched to:\n<code>{html.escape(runner.workspace_dir)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
    else:
        await update.message.reply_text(
            f"❌ Directory not found:\n<code>{html.escape(target_path)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    await update.message.reply_text(
        f"📁 Current Workspace:\n<code>{html.escape(runner.workspace_dir)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=QUICK_ACTION_KEYBOARD,
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    runner.reset_conversation()
    await update.message.reply_text(
        "🔄 <b>Conversation session reset.</b>\nNext prompt will start a clean turn.",
        parse_mode=ParseMode.HTML,
        reply_markup=QUICK_ACTION_KEYBOARD,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    chat_id = update.effective_chat.id
    if stream_manager:
        session = stream_manager.get_session(chat_id)
        if session and session.is_active:
            await session.cancel()

    if not runner.is_running:
        await update.message.reply_text(
            "ℹ️ No active Antigravity task is currently running.",
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    killed = await runner.cancel()
    if killed:
        await update.message.reply_text(
            "🛑 <b>Active task killed successfully.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
    else:
        await update.message.reply_text(
            "⚠️ Could not kill process (it may have already completed).",
            reply_markup=QUICK_ACTION_KEYBOARD,
        )


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    user_prompt = update.message.text.strip()
    if not user_prompt:
        return

    chat_id = update.effective_chat.id

    # 1. Quick-Action Bottom Bar Keyboard Button Interception
    prompt_norm = user_prompt.strip()
    if prompt_norm in ("📊 Status", "status"):
        await cmd_status(update, context)
        return
    elif prompt_norm in ("📜 Sessions", "sessions"):
        await cmd_sessions(update, context)
        return
    elif prompt_norm in ("📸 Screenshot", "screenshot"):
        await cmd_screenshot(update, context)
        return
    elif prompt_norm in ("📁 PWD", "pwd"):
        await cmd_pwd(update, context)
        return
    elif prompt_norm in ("🔄 New Turn", "new"):
        await cmd_new(update, context)
        return
    elif prompt_norm in ("🛑 Stop Task", "stop", "cancel"):
        await cmd_stop(update, context)
        return

    # 2. Shortcut handling for 'attach'
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
                    reply_markup=QUICK_ACTION_KEYBOARD,
                )
                return

    # 3. Check if an interactive terminal window is open on desktop
    interactive_pid = find_interactive_agy_pid()
    if interactive_pid and stream_manager:
        session = await stream_manager.start_session(
            chat_id=chat_id,
            title="Antigravity Live PC Screen",
            initial_status="Injecting Prompt...",
            initial_prompt=user_prompt,
        )
        injected = inject_text_to_agy(user_prompt, pid=interactive_pid)
        if injected:
            session.feed(
                f"Prompt injected to desktop terminal PID {interactive_pid}:\n"
                f"> {user_prompt}\n\n"
                f"Waiting for live tool execution logs...\n"
            )
            return

    # 4. Headless execution fallback
    if runner.is_running:
        await update.message.reply_text(
            "⚠️ An Antigravity task is already executing. Send /stop to cancel it first.",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    assert stream_manager is not None
    session_title = f"Antigravity Session ({runner.conversation_id[:8]}...)" if runner.conversation_id else "Antigravity Session"

    # Step 1: Session starts -> Send persistent message and store chat_id and message_id
    session = await stream_manager.start_session(
        chat_id=chat_id,
        title=session_title,
        initial_status="Started",
        initial_prompt=user_prompt,
        edit_interval=1.0,
        buffer_debounce=0.5,
    )

    # Step 2 & 3 & 4: Output arrives continuously from process -> buffered & edited ~1s
    result = await runner.execute_prompt(user_prompt, on_chunk=session.feed)

    # Step 5: Task completes or important events occur
    if result.is_cancelled:
        await session.cancel()
        return

    if result.error_message:
        await session.fail(result.error_message)
        return

    final_text = result.full_output.strip() or "(Task completed with empty output)"
    conv_footer = f"\n\n<i>Session: <code>{runner.conversation_id}</code></i>" if runner.conversation_id else ""
    formatted_html = markdown_to_telegram_html(final_text)

    # Send separate completion notification
    event_notification = f"✅ <b>Task Completed:</b>\n\n{formatted_html}{conv_footer}"
    await session.complete(
        final_status="Completed",
        event_notification=event_notification,
        full_output=result.full_output,
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
    """Initializes and starts the hybrid streaming engine and transcript mirror watcher."""
    global stream_manager
    stream_manager = TerminalStreamManager(bot=application.bot)
    application.bot_data["stream_manager"] = stream_manager

    async def on_pc_user(conv_id: str, prompt: str):
        for user_id in ALLOWED_USER_IDS:
            try:
                await stream_manager.start_session(
                    chat_id=user_id,
                    title="Antigravity PC Screen Session",
                    initial_status="User Input Detected",
                    initial_prompt=prompt,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize PC stream session: {e}")

    async def on_pc_activity_step(conv_id: str, bullet: str):
        """Streams live tool execution and thoughts using Hybrid Message Editing."""
        for user_id in ALLOWED_USER_IDS:
            session = stream_manager.get_session(user_id)
            if not session or not session.is_active:
                session = await stream_manager.start_session(
                    chat_id=user_id,
                    title="Antigravity PC Screen Session",
                    initial_status="Working...",
                )
            session.feed(bullet + "\n")

    async def on_pc_model(conv_id: str, content: str, all_bullets: List[str]):
        """Step 5: Completes persistent session and delivers separate event notification."""
        formatted_html = markdown_to_telegram_html(content)
        steps_summary = ""
        if all_bullets:
            steps_joined = "\n".join(all_bullets[-8:])
            steps_summary = f"📋 <b>Execution Log:</b>\n<blockquote>{steps_joined}</blockquote>\n\n"

        event_notification = f"{steps_summary}🤖 <b>[Antigravity Response]</b>\n\n{formatted_html}"

        for user_id in ALLOWED_USER_IDS:
            session = stream_manager.get_session(user_id)
            if session and session.is_active:
                await session.complete(
                    final_status="Completed",
                    event_notification=event_notification,
                    full_output=content,
                )
            else:
                try:
                    if len(event_notification) <= 3900:
                        await application.bot.send_message(
                            chat_id=user_id,
                            text=event_notification,
                            parse_mode=ParseMode.HTML,
                            reply_markup=QUICK_ACTION_KEYBOARD,
                        )
                    else:
                        doc = io.BytesIO(content.encode("utf-8"))
                        doc.name = "antigravity_pc_output.txt"
                        await application.bot.send_message(
                            chat_id=user_id,
                            text="🤖 <b>[Antigravity Response]</b>\n<i>(Output attached below due to length)</i>",
                            parse_mode=ParseMode.HTML,
                            reply_markup=QUICK_ACTION_KEYBOARD,
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
    logger.info("Hybrid streaming manager and transcript mirror watcher active.")


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

    logger.info("Starting Antigravity Telegram Bot with Persistent Quick-Action Keyboard & Screenshot...")
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
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("cancel", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    app.add_error_handler(global_error_handler)

    logger.info("Bot is polling with Quick-Action Keyboard and Screenshot Engine...")
    app.run_polling()


if __name__ == "__main__":
    main()
