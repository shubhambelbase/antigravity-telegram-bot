"""Autonomous Antigravity Telegram Bot Remote Control.

Provides a full remote control center for Google Antigravity CLI:
1. CLI Connection: Live status monitoring (Desktop Terminal vs Headless).
2. Terminal Controls: Normal command input, instant keystroke injection.
3. Interactive Prompts: Inline keypad for Yes / No / Select (1, 2, 3), Arrows, and Ctrl+C.
4. Live Output: Hybrid streaming terminal view with 1s updates.
5. Session History & Logs: /history inspection and /logs export/download.
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
from execution.autostart import disable_autostart, enable_autostart, is_autostart_enabled
from execution.console_injector import (
    find_interactive_agy_pid,
    inject_special_key,
    inject_text_to_agy,
)
from execution.formatter import markdown_to_telegram_html
from execution.screenshot import get_screenshot
from execution.stream_manager import TerminalStreamManager, collapse_consecutive_lines
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
        [KeyboardButton("📁 PWD"), KeyboardButton("🎮 Controls"), KeyboardButton("🛑 Stop Task")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def get_interactive_controls_markup() -> InlineKeyboardMarkup:
    """Generates the interactive terminal keypad for Yes/No/Select/Navigation."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes (Y)", callback_data="key:yes"),
            InlineKeyboardButton("❌ No (N)", callback_data="key:no"),
            InlineKeyboardButton("⏎ Enter", callback_data="key:enter"),
        ],
        [
            InlineKeyboardButton("⬆️ Up", callback_data="key:up"),
            InlineKeyboardButton("⬇️ Down", callback_data="key:down"),
            InlineKeyboardButton("␣ Space", callback_data="key:space"),
        ],
        [
            InlineKeyboardButton("1️⃣ Select 1", callback_data="key:1"),
            InlineKeyboardButton("2️⃣ Select 2", callback_data="key:2"),
            InlineKeyboardButton("3️⃣ Select 3", callback_data="key:3"),
        ],
        [
            InlineKeyboardButton("🛑 Ctrl+C", callback_data="key:ctrl_c"),
            InlineKeyboardButton("⌫ Backspace", callback_data="key:backspace"),
            InlineKeyboardButton("📸 Screenshot", callback_data="key:screenshot"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


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
    screen_status = f"🟢 Connected (PID {interactive_pid})" if interactive_pid else "⚪ Headless Runner"
    conv_text = f"<code>{runner.conversation_id[:8]}...</code>" if runner.conversation_id else "Auto-Tracking"

    welcome_text = (
        f"⚡ <b>Antigravity Remote Control Online</b>\n\n"
        f"<b>CLI Connection:</b> {screen_status}\n"
        f"<b>Active Session:</b> {conv_text}\n"
        f"<b>Workspace:</b> <code>{html.escape(runner.workspace_dir)}</code>\n\n"
        f"<b>Terminal Controls:</b>\n"
        f"• Type any normal command to execute live\n"
        f"• 🎮 <b>/controls</b> - Interactive keypad for Yes/No/Select/Arrows\n"
        f"• 📜 <b>/sessions</b> - Switch sessions or export logs\n"
        f"• 📑 <b>/history</b> - View recent conversation turns\n"
        f"• 📄 <b>/logs</b> - Download complete session transcript\n"
        f"• 📸 <b>/screenshot</b> - Live desktop/terminal screen view\n"
        f"• 📁 <b>/pwd</b> &amp; <b>/cd &lt;path&gt;</b> - Workspace navigation\n"
        f"• 🛑 <b>/stop</b> - Kill active task immediately"
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


async def cmd_controls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the interactive terminal keypad for Yes/No/Select/Navigation."""
    if not await check_auth(update):
        return

    interactive_pid = find_interactive_agy_pid()
    status_text = f"🟢 Connected (PID {interactive_pid})" if interactive_pid else "⚪ Headless"

    msg = (
        f"🎮 <b>Antigravity Remote Keypad</b>\n\n"
        f"<b>CLI Connection:</b> {status_text}\n"
        f"<i>Tap any button below to inject actions directly into your active terminal:</i>"
    )
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_interactive_controls_markup(),
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

    lines = ["📜 <b>Antigravity Session History:</b>\n"]
    keyboard = []

    for idx, s in enumerate(recents, 1):
        is_active = " <b>[ACTIVE]</b>" if runner.conversation_id == s.conv_id else ""
        lines.append(
            f"<b>{idx}.</b> <code>{s.conv_id[:8]}...</code> ({s.updated_at}){is_active}\n"
            f"   <i>\"{html.escape(s.preview)}\"</i>\n"
        )
        attach_label = f"✅ Active #{idx}" if runner.conversation_id == s.conv_id else f"🔗 Attach #{idx}"
        keyboard.append([
            InlineKeyboardButton(attach_label, callback_data=f"attach:{s.conv_id}"),
            InlineKeyboardButton(f"📄 Logs #{idx}", callback_data=f"logs:{s.conv_id}"),
        ])

    lines.append("<i>Tap 'Attach' to continue session, or 'Logs' to inspect history:</i>")
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays recent conversation turns for the active session."""
    if not await check_auth(update):
        return

    limit = 5
    if context.args and context.args[0].isdigit():
        limit = min(15, max(1, int(context.args[0])))

    turns = runner.get_session_turns(limit=limit)
    if not turns:
        await update.message.reply_text(
            "ℹ️ No recorded conversation turns found for active session.",
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    lines = [f"📜 <b>Session History (Last {len(turns)} Turns):</b>\n"]
    for i, t in enumerate(turns, 1):
        u_preview = t["user"].replace("\n", " ")
        if len(u_preview) > 90:
            u_preview = u_preview[:87] + "..."
        m_preview = t["model"].replace("\n", " ") if t["model"] else "(Turn in progress or tool actions only)"
        if len(m_preview) > 120:
            m_preview = m_preview[:117] + "..."

        lines.append(
            f"<b>Turn {i}</b> <i>[{html.escape(t['timestamp'])}]</i>\n"
            f"👤 <b>User:</b> {html.escape(u_preview)}\n"
            f"🤖 <b>Agent:</b> {html.escape(m_preview)} <i>(Tools: {t['tools_count']})</i>\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=QUICK_ACTION_KEYBOARD)


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports and sends session execution logs."""
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    conv_id = context.args[0].strip() if context.args else None
    target_id = conv_id or runner.conversation_id or runner._get_latest_conversation_id()

    if not target_id:
        await msg.reply_text("ℹ️ No active session to export logs from.", reply_markup=QUICK_ACTION_KEYBOARD)
        return

    log_content = runner.get_session_log_export(conv_id=target_id, max_lines=250)

    if len(log_content) <= 3500:
        await msg.reply_text(
            f"📄 <b>Session Execution Log (<code>{target_id[:8]}...</code>):</b>\n\n"
            f"<pre><code>{html.escape(log_content)}</code></pre>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
    else:
        doc = io.BytesIO(log_content.encode("utf-8"))
        doc.name = f"session_{target_id[:8]}_log.txt"
        await msg.reply_document(
            document=doc,
            caption=f"📄 Full session execution log ({target_id[:8]}...)",
            reply_markup=QUICK_ACTION_KEYBOARD,
        )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    user = update.effective_user
    if not user or not is_authorized(user.id):
        await query.answer("Unauthorized", show_alert=True)
        return

    data = query.data or ""

    # 1. Interactive Keypad Injections
    if data.startswith("key:"):
        key_name = data.split("key:", 1)[1]
        if key_name == "screenshot":
            await query.answer("Capturing screenshot...")
            await cmd_screenshot(update, context)
            return

        ok = inject_special_key(key_name)
        if ok:
            await query.answer(f"Sent: {key_name.upper()}")
        else:
            await query.answer(f"Failed to send {key_name} (No active desktop terminal)", show_alert=True)
        return

    # 2. Attach Session
    elif data.startswith("attach:"):
        await query.answer()
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

    # 3. Export Logs for Session
    elif data.startswith("logs:"):
        await query.answer("Fetching logs...")
        conv_id = data.split("logs:", 1)[1]
        context.args = [conv_id]
        await cmd_logs(update, context)

    # 4. Workspace Navigation
    elif data.startswith("ws:"):
        ws_action = data.split("ws:", 1)[1]
        if ws_action == "up":
            parent = runner.get_parent_workspace()
            if parent:
                runner.set_workspace(parent)
                await query.answer(f"Switched to {os.path.basename(parent) or parent}")
                text, markup = build_workspace_view(runner)
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            else:
                await query.answer("Already at drive root", show_alert=True)
            return

        elif ws_action.startswith("sub:"):
            try:
                idx = int(ws_action.split("sub:", 1)[1])
                subdirs = runner.get_workspace_subdirs(limit=6)
                if 0 <= idx < len(subdirs):
                    chosen = subdirs[idx]
                    runner.set_workspace(chosen)
                    await query.answer(f"Switched to {chosen}")
                    text, markup = build_workspace_view(runner)
                    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
                else:
                    await query.answer("Folder not found", show_alert=True)
            except Exception as e:
                logger.debug(f"Subdir switch error: {e}")
            return

        elif ws_action.startswith("rec:"):
            try:
                idx = int(ws_action.split("rec:", 1)[1])
                other_recents = [
                    p for p in runner.recent_workspaces
                    if os.path.abspath(p) != os.path.abspath(runner.workspace_dir)
                ][:2]
                if 0 <= idx < len(other_recents):
                    chosen = other_recents[idx]
                    runner.set_workspace(chosen)
                    await query.answer(f"Switched to {os.path.basename(chosen) or chosen}")
                    text, markup = build_workspace_view(runner)
                    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
                else:
                    await query.answer("Recent workspace not found", show_alert=True)
            except Exception as e:
                logger.debug(f"Recent switch error: {e}")
            return

        elif ws_action == "drives":
            await query.answer()
            text, markup = build_drives_view(runner)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            return

        elif ws_action.startswith("drive:"):
            letter = ws_action.split("drive:", 1)[1]
            drive_path = f"{letter}:\\"
            if runner.set_workspace(drive_path):
                await query.answer(f"Switched to {drive_path}")
                text, markup = build_workspace_view(runner)
                await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            else:
                await query.answer(f"Drive {drive_path} not accessible", show_alert=True)
            return

        elif ws_action == "mkdir":
            pending = context.user_data.get("pending_mkdir")
            if pending and runner.create_and_set_workspace(pending):
                context.user_data.pop("pending_mkdir", None)
                await query.answer("Directory created!")
                text, markup = build_workspace_view(runner)
                await query.edit_message_text(
                    f"📁 <b>Created & switched to workspace:</b>\n<code>{html.escape(runner.workspace_dir)}</code>\n\n{text}",
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await query.answer("Could not create directory", show_alert=True)
            return

        elif ws_action == "refresh":
            await query.answer("Refreshed")
            text, markup = build_workspace_view(runner)
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            return

        elif ws_action == "close":
            await query.answer()
            await query.edit_message_reply_markup(reply_markup=None)
            return

    # 5. Live Sync Toggle
    elif data == "sync:toggle":
        watcher: Optional[TranscriptWatcher] = context.application.bot_data.get("watcher")
        if watcher:
            if watcher.is_enabled:
                watcher.pause()
            else:
                watcher.resume()
            sync_enabled = watcher.is_enabled
            status_text = (
                "🟢 <b>Live Sync: ENABLED</b>\n<i>PC terminal activity, thoughts, and output are mirrored live to Telegram.</i>"
                if sync_enabled
                else "⚪ <b>Live Sync: DISABLED (Silent Mode)</b>\n<i>PC activity is paused. The bot will only respond to messages sent directly in this Telegram chat.</i>"
            )
            toggle_btn = InlineKeyboardButton(
                "🔕 Mute Live Sync" if sync_enabled else "🔔 Enable Live Sync",
                callback_data="sync:toggle"
            )
            await query.answer("Live Sync Toggled")
            await query.edit_message_text(status_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[toggle_btn]]))
        else:
            await query.answer("Live sync service not initialized", show_alert=True)
        return

    # 6. Auto-Start Toggle
    elif data == "autostart:toggle":
        is_on = is_autostart_enabled()
        if is_on:
            disable_autostart()
        else:
            enable_autostart()
        new_state = is_autostart_enabled()
        status_text = (
            "🚀 <b>Windows Auto-Start: ENABLED</b>\n<i>The Antigravity bot will launch silently in the background whenever you boot or log in to your laptop.</i>"
            if new_state
            else "⚪ <b>Windows Auto-Start: DISABLED</b>\n<i>The bot will no longer start automatically when Windows boots.</i>"
        )
        toggle_btn = InlineKeyboardButton(
            "🛑 Disable Auto-Start" if new_state else "🚀 Enable Auto-Start",
            callback_data="autostart:toggle"
        )
        await query.answer("Auto-Start Updated")
        await query.edit_message_text(status_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[toggle_btn]]))
        return


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


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles or sets live PC sync mirror on/off."""
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    watcher: Optional[TranscriptWatcher] = context.application.bot_data.get("watcher")
    if not watcher:
        await msg.reply_text("ℹ️ Live sync service is not active.")
        return

    arg = context.args[0].lower() if context.args else None
    if arg in ("off", "disable", "stop", "pause", "mute"):
        watcher.pause()
    elif arg in ("on", "enable", "start", "resume", "unmute"):
        watcher.resume()
    else:
        # Toggle
        if watcher.is_enabled:
            watcher.pause()
        else:
            watcher.resume()

    sync_enabled = watcher.is_enabled
    status_text = (
        "🟢 <b>Live Sync: ENABLED</b>\n<i>PC terminal activity, thoughts, and outputs are mirrored live to Telegram.</i>"
        if sync_enabled
        else "⚪ <b>Live Sync: DISABLED (Silent Mode)</b>\n<i>PC activity is paused. The bot will only respond to messages sent directly in this Telegram chat.</i>"
    )
    toggle_btn = InlineKeyboardButton(
        "🔕 Mute Live Sync" if sync_enabled else "🔔 Enable Live Sync",
        callback_data="sync:toggle"
    )
    await msg.reply_text(
        status_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[toggle_btn]]),
    )


async def cmd_autostart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables, disables, or toggles auto-start on Windows boot."""
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    arg = context.args[0].lower() if context.args else None
    if arg in ("on", "enable", "start", "yes", "1"):
        enable_autostart()
    elif arg in ("off", "disable", "stop", "no", "0"):
        disable_autostart()
    else:
        # Toggle
        if is_autostart_enabled():
            disable_autostart()
        else:
            enable_autostart()

    new_state = is_autostart_enabled()
    status_text = (
        "🚀 <b>Windows Auto-Start: ENABLED</b>\n<i>The Antigravity bot will launch silently in the background whenever you boot or log in to your laptop.</i>"
        if new_state
        else "⚪ <b>Windows Auto-Start: DISABLED</b>\n<i>The bot will no longer start automatically when Windows boots.</i>"
    )
    toggle_btn = InlineKeyboardButton(
        "🛑 Disable Auto-Start" if new_state else "🚀 Enable Auto-Start",
        callback_data="autostart:toggle"
    )
    await msg.reply_text(
        status_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[toggle_btn]]),
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

    watcher: Optional[TranscriptWatcher] = context.application.bot_data.get("watcher")
    sync_enabled = watcher.is_enabled if watcher else False
    sync_desc = "🟢 Active (Live Mirror)" if sync_enabled else "⚪ Paused (Silent Mode)"

    autostart_on = is_autostart_enabled()
    auto_desc = "🟢 Enabled (Runs on Windows boot)" if autostart_on else "⚪ Disabled"

    status_msg = (
        f"📊 <b>System & Remote Control Status</b>\n\n"
        f"<b>CLI Connection:</b> {screen_status}\n"
        f"<b>Agent Status:</b> {agent_state}\n"
        f"<b>Live PC Sync:</b> {sync_desc}\n"
        f"<b>Auto-Start:</b> {auto_desc}\n"
        f"<b>Workspace:</b> <code>{html.escape(runner.workspace_dir)}</code>\n"
        f"<b>Active Session:</b> {conv_text}\n"
        f"<b>Terminal Engine:</b> 🟢 Live Output Streaming + Paced Keystroke Injector\n"
        f"<b>Host CPU:</b> {cpu_pct}%\n"
        f"<b>Host RAM:</b> {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)"
    )
    sync_btn = InlineKeyboardButton(
        "🔕 Mute Live Sync" if sync_enabled else "🔔 Enable Live Sync",
        callback_data="sync:toggle"
    )
    auto_btn = InlineKeyboardButton(
        "🛑 Disable Auto-Start" if autostart_on else "🚀 Enable Auto-Start",
        callback_data="autostart:toggle"
    )
    await update.message.reply_text(
        status_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[sync_btn, auto_btn]]),
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    chat_id = update.effective_chat.id
    active_terminal_text = None
    if stream_manager:
        session = stream_manager.get_session(chat_id)
        if session:
            active_terminal_text = session.get_full_buffer_text()

    status_msg = await msg.reply_text(
        "📸 <i>Capturing screen snapshot...</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        interactive_pid = find_interactive_agy_pid()
        title = f"Antigravity Terminal (PID {interactive_pid})" if interactive_pid else "Antigravity Console"
        png_bytes, caption = get_screenshot(fallback_terminal_text=active_terminal_text, title=title)

        photo_stream = io.BytesIO(png_bytes)
        photo_stream.name = "screenshot.png"

        await msg.reply_photo(
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


def build_workspace_view(runner_instance: AntigravityRunner) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds an interactive workspace navigation card with inline folder buttons."""
    current = runner_instance.workspace_dir
    parent = runner_instance.get_parent_workspace()
    subdirs = runner_instance.get_workspace_subdirs(limit=6)

    text = (
        f"📁 <b>Active Workspace:</b>\n"
        f"<code>{html.escape(current)}</code>\n\n"
        f"📂 <b>Folder Navigation:</b>\n"
        f"<i>Tap any folder to enter, or send <code>/cd &lt;path&gt;</code></i>"
    )

    keyboard: List[List[InlineKeyboardButton]] = []

    # 1. Parent directory button
    if parent:
        parent_name = os.path.basename(parent) or parent
        keyboard.append([InlineKeyboardButton(f"📂 ⬆️ Parent ({parent_name})", callback_data="ws:up")])

    # 2. Child directories (2 per row)
    row: List[InlineKeyboardButton] = []
    for idx, folder in enumerate(subdirs):
        display = folder if len(folder) <= 18 else folder[:16] + ".."
        row.append(InlineKeyboardButton(f"📁 {display}", callback_data=f"ws:sub:{idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # 3. Recent workspaces (up to 2)
    other_recents = [
        p for p in runner_instance.recent_workspaces
        if os.path.abspath(p) != os.path.abspath(current)
    ][:2]
    for idx, rpath in enumerate(other_recents):
        rname = os.path.basename(rpath) or rpath
        keyboard.append([InlineKeyboardButton(f"🕒 Switch: {rname}", callback_data=f"ws:rec:{idx}")])

    # 4. System drives & tools
    keyboard.append([
        InlineKeyboardButton("💾 Drives", callback_data="ws:drives"),
        InlineKeyboardButton("🔄 Refresh", callback_data="ws:refresh"),
        InlineKeyboardButton("❌ Close", callback_data="ws:close"),
    ])

    return text, InlineKeyboardMarkup(keyboard)


def build_drives_view(runner_instance: AntigravityRunner) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds drive selection keyboard."""
    drives = runner_instance.get_available_drives()
    text = (
        f"💾 <b>Available System Drives:</b>\n"
        f"Current: <code>{html.escape(runner_instance.workspace_dir)}</code>\n\n"
        f"<i>Tap a drive to switch workspace:</i>"
    )

    keyboard: List[List[InlineKeyboardButton]] = []
    drive_row: List[InlineKeyboardButton] = []
    for drive in drives:
        letter = drive.replace(":\\", "").replace(":", "").replace("\\", "").strip()
        drive_row.append(InlineKeyboardButton(f"💾 {drive}", callback_data=f"ws:drive:{letter}"))
        if len(drive_row) == 3:
            keyboard.append(drive_row)
            drive_row = []
    if drive_row:
        keyboard.append(drive_row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Workspace", callback_data="ws:refresh")])
    return text, InlineKeyboardMarkup(keyboard)


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    if not context.args:
        text, markup = build_workspace_view(runner)
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    if runner.is_running:
        await msg.reply_text(
            "⚠️ An Antigravity task is currently executing. Use /stop first before changing workspace.",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    target_path = " ".join(context.args).strip('"').strip("'")
    if runner.set_workspace(target_path):
        text, markup = build_workspace_view(runner)
        header = (
            f"✅ <b>Workspace switched to:</b>\n"
            f"<code>{html.escape(runner.workspace_dir)}</code>\n\n"
            f"<i>Next prompts will execute in this directory with a clean session.</i>\n\n"
        )
        await msg.reply_text(
            f"{header}{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    else:
        resolved = runner.resolve_path(target_path)
        context.user_data["pending_mkdir"] = resolved
        mkdir_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Create & Switch Here", callback_data="ws:mkdir")],
            [InlineKeyboardButton("📁 View Current Workspace", callback_data="ws:refresh")],
        ])
        await msg.reply_text(
            f"❌ <b>Directory not found:</b>\n<code>{html.escape(resolved)}</code>\n\n"
            f"Would you like to create this directory and switch into it?",
            parse_mode=ParseMode.HTML,
            reply_markup=mkdir_markup,
        )


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if msg:
        text, markup = build_workspace_view(runner)
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )


async def cmd_mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    if not context.args:
        await msg.reply_text(
            "Usage: <code>/mkdir &lt;folder_name or path&gt;</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    target_path = " ".join(context.args).strip('"').strip("'")
    if runner.create_and_set_workspace(target_path):
        text, markup = build_workspace_view(runner)
        await msg.reply_text(
            f"📁 <b>Created & switched to workspace:</b>\n<code>{html.escape(runner.workspace_dir)}</code>\n\n{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    else:
        await msg.reply_text(
            f"❌ Failed to create directory: <code>{html.escape(target_path)}</code>",
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

    # Also attempt sending Ctrl+C into open interactive terminal
    interactive_pid = find_interactive_agy_pid()
    if interactive_pid:
        inject_special_key("ctrl_c", pid=interactive_pid)

    if not runner.is_running:
        await update.message.reply_text(
            "🛑 <b>Stop signal sent.</b> (Interactive terminal interrupted / idle runner)",
            parse_mode=ParseMode.HTML,
            reply_markup=QUICK_ACTION_KEYBOARD,
        )
        return

    killed = await runner.cancel()
    if killed:
        await update.message.reply_text(
            "🛑 <b>Active headless task killed successfully.</b>",
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
    elif prompt_norm in ("📁 PWD", "pwd", "workspace", "/workspace"):
        await cmd_pwd(update, context)
        return
    elif prompt_norm.lower().startswith("cd ") or prompt_norm.lower() == "cd":
        target = user_prompt[3:].strip() if prompt_norm.lower().startswith("cd ") else ""
        context.args = target.split() if target else []
        await cmd_cd(update, context)
        return
    elif prompt_norm in ("🎮 Controls", "controls", "keypad"):
        await cmd_controls(update, context)
        return
    elif prompt_norm in ("🛑 Stop Task", "stop", "cancel"):
        await cmd_stop(update, context)
        return
    elif prompt_norm in ("history", "/history"):
        await cmd_history(update, context)
        return
    elif prompt_norm in ("logs", "/logs"):
        await cmd_logs(update, context)
        return
    elif prompt_norm in ("sync", "/sync", "livesync", "/livesync", "mute", "/mute", "unmute", "/unmute"):
        await cmd_sync(update, context)
        return
    elif prompt_norm in ("autostart", "/autostart", "startup", "/startup", "boot"):
        await cmd_autostart(update, context)
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
        else:
            session.feed(
                f"⚠️ Direct console injection failed on PID {interactive_pid}.\n"
                f"Automatically falling back to autonomous runner...\n\n"
            )

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

    # Step 1: Session starts -> Send persistent message if not already active
    session = stream_manager.get_session(chat_id)
    if not session or not session.is_active:
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

    # Send separate completion notification with interactive keypad
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
                session = stream_manager.get_session(user_id)
                if session and session.is_active:
                    session._status = "Working..."
                    session.progress.operation_title = prompt
                else:
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
            collapsed_bullets = collapse_consecutive_lines(all_bullets)
            steps_joined = "\n".join(collapsed_bullets[-8:])
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
                            reply_markup=get_interactive_controls_markup(),
                        )
                    else:
                        doc = io.BytesIO(content.encode("utf-8"))
                        doc.name = "antigravity_pc_output.txt"
                        await application.bot.send_message(
                            chat_id=user_id,
                            text="🤖 <b>[Antigravity Response]</b>\n<i>(Output attached below due to length)</i>",
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_interactive_controls_markup(),
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
        get_active_conv_id=lambda: runner.conversation_id or runner._get_latest_conversation_id(),
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

    logger.info("Starting Antigravity Remote Control with Interactive Controls & Session History...")
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
    app.add_handler(CommandHandler("autostart", cmd_autostart))
    app.add_handler(CommandHandler("startup", cmd_autostart))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("livesync", cmd_sync))
    app.add_handler(CommandHandler("mute", cmd_sync))
    app.add_handler(CommandHandler("unmute", cmd_sync))
    app.add_handler(CommandHandler("controls", cmd_controls))
    app.add_handler(CommandHandler("keys", cmd_controls))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("workspace", cmd_pwd))
    app.add_handler(CommandHandler("mkdir", cmd_mkdir))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("cancel", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    app.add_error_handler(global_error_handler)

    logger.info("Antigravity Remote Control is polling with interactive terminal controls...")
    app.run_polling()


if __name__ == "__main__":
    main()
