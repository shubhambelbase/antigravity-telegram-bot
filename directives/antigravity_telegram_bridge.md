# Directive: Antigravity Telegram Bridge

## Purpose
Provide a secure, reliable, autonomous Telegram bot interface to control the Google Antigravity CLI (`agy`) remotely from any Telegram client, with bidirectional real-time mirroring and direct console keystroke injection.

## Operating Architecture
- **Layer 1 (Directive)**: This SOP defines operational parameters, security constraints, and command expectations.
- **Layer 2 (Orchestration)**: `execution/telegram_bot.py` listens to incoming Telegram messages, enforces authentication, manages sessions, and routes prompts either to active console injection or headless execution.
- **Layer 3 (Execution)**:
  - `execution/console_injector.py`: Injects prompts directly into the running desktop terminal window via Win32 `AttachConsole` and `WriteConsoleInputW`.
  - `execution/transcript_watcher.py`: Tails the active conversation `transcript.jsonl` in real-time to mirror PC terminal prompts, thoughts, and tool execution logs to Telegram.
  - `execution/agy_runner.py`: Manages fallback headless subprocess execution of `agy.exe`, captures real-time outputs, handles cancellation/timeouts, and streams updates back.
  - `execution/formatter.py`: Sanitizes and converts markdown output to clean Telegram HTML.

## Commands Supported
- `/start` - Initial welcome, user ID verification, pairing status.
- `/claim <user_id>` - Auto-claims the bot during first-run setup.
- `/sessions` - Lists recent sessions with 1-click inline buttons.
- `/attach <1-5 or ID>` - Attaches to any existing conversation with full history.
- `/status` - Current workspace, conversation ID, active execution status, system CPU/RAM.
- `/cd <path>` - Changes current workspace directory.
- `/pwd` - Shows current working directory.
- `/new` - Resets conversation ID to start a fresh agent session.
- `/stop` or `/cancel` - Terminates the active running agent process.
- `<any prompt>` - Types into the active PC terminal screen (or runs headlessly if no terminal is open).

## Safety Rules
- Only authorized user IDs listed in `ALLOWED_TELEGRAM_USER_IDS` can execute commands or send prompts.
- Single-instance PID file lock prevents duplicate polling conflicts.
- Rate-limited message editing (min 1.5s interval) prevents Telegram HTTP 429 FloodWait errors.
- Unhandled exceptions are routed to `global_error_handler` without crashing the daemon.
