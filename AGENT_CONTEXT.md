# Project Context: Antigravity Telegram Bot

## Overview
A lightweight, reliable, autonomous Telegram bot controller for Google Antigravity CLI (`agy`). Enables remote execution of coding tasks, project navigation, conversation history resumption with 1-click inline buttons, rich Markdown formatting, real-time PC transcript mirroring with live terminal-like tool execution logs (Thought/Ran/Edited/Created/Read), rate-limiting safeguards, and direct Win32 console keystroke injection into the active desktop terminal.

## Stack & Environment
- **OS**: Windows
- **Python**: 3.14 (.venv in project root)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pytest`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe`)

## Architecture & Layout
- `directives/` - Standard Operating Procedures:
  - `antigravity_telegram_bridge.md`: Execution rules, timeouts, safety protocols.
- `execution/` - Core Python services:
  - `console_injector.py`: Win32 `AttachConsole` and `WriteConsoleInputW` injector typing prompts into the active desktop terminal screen.
  - `transcript_watcher.py`: Real-time asynchronous transcript observer tailing `transcript.jsonl` to detect desktop PC interactions, extracting tool calls and thinking traces, and pushing them to Telegram.
  - `agy_runner.py`: Subprocess manager wrapping `agy -p` with conversation resumption, session discovery (`get_recent_conversations`), attach controls, and abort handling.
  - `telegram_bot.py`: Telegram long-polling bot with user whitelist security, throttled message streaming, inline buttons, `/sessions`, `/attach` commands, PID file single-instance lock, and rate-limited live tool updates.
  - `formatter.py`: Converts Markdown output to native Telegram HTML.
- `setup/` - Automated setup & guides:
  - `install.bat`: 1-click Windows installer (detects/installs Python via winget if missing, creates `.venv`, installs requirements, runs test suite, copies `.env.example`, pauses at end).
  - `setup_guide.md`: Complete step-by-step documentation for users cloning the repo.
- `tests/` - Unit tests:
  - `test_runner.py`: Tests runner initialization, workspace switching, session resets, and conversation discovery.
  - `test_formatter.py`: Tests Markdown-to-HTML conversion.
  - `test_watcher.py`: Tests live transcript change detection, tool call extraction, and dispatching.
  - `test_injector.py`: Tests process detection and injection safety fallback.
- `.tmp/` - Temporary files and process run logs.
- `.env` - Environment secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`).
- `run_bot.bat` - Windows single-click launcher.
- `install.bat` - Root wrapper for `setup/install.bat`.

## Commands Supported
- `/start` - Initial verification, setup / claim instructions, command list.
- `/claim <user_id>` - Auto-claims the bot during first-run setup if unconfigured.
- `/sessions` - Lists recent Antigravity conversation sessions with 1-click inline buttons.
- `/attach <1-5 or ID>` - Attaches Telegram to any existing conversation with full history.
- `/status` - Current workspace, active conversation ID, PC screen control status, live tool logs state, CPU/RAM.
- `/cd <path>` - Changes current workspace path.
- `/pwd` - Shows current workspace directory.
- `/new` - Starts a clean conversation context.
- `/stop` or `/cancel` - Kills the currently active agent turn immediately.
- Plain text - Types prompt directly into the active PC terminal screen (or runs headlessly if no terminal is open).

## Status & Next Steps
- Status: Fully verified installer fix, all 13 tests passing (100% success), clean git tree. Bot polling operational.
- Last updated: 2026-11-15.
