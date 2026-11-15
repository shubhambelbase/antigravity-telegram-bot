# Project Context: Antigravity Telegram Bot

## Overview
A lightweight, reliable, autonomous Telegram remote control center for Google Antigravity CLI (`agy`). Features real-time CLI connection detection, normal command execution, interactive prompts (Yes / No / Select / Navigation keys), live hybrid streaming output with 1-second edits, and full session history / logs inspection.

## Stack & Environment
- **OS**: Windows
- **Python**: 3.14 (.venv in project root)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pillow` (v13+), `pytest`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe`)

## Architecture & Layout
- `directives/` - Standard Operating Procedures:
  - `antigravity_telegram_bridge.md`: Execution rules, timeouts, safety protocols.
- `execution/` - Core Python services:
  - `console_injector.py`: Win32 `AttachConsole`, `VkKeyScanW`, `MapVirtualKeyW`, and `WriteConsoleInputW` injector typing normal prompts and interactive keys (Yes/No/Select/Arrows/Ctrl+C).
  - `screenshot.py`: Desktop screen capture utility (PIL ImageGrab / PowerShell) and high-fidelity dark-mode terminal window snapshot renderer.
  - `stream_manager.py`: Hybrid Message Editing + Event-Based Streaming manager. Maintains persistent live terminal message with 500ms debounce buffer, ~1.0s `editMessageText` updates, and separate event notifications for completions/errors.
  - `transcript_watcher.py`: Real-time asynchronous transcript observer tailing `transcript.jsonl` with safe HTML entity escaping, auto-detecting latest sessions, and extracting tool calls/thoughts.
  - `agy_runner.py`: Subprocess manager wrapping `agy -p` with conversation resumption, session discovery (`get_recent_conversations`), non-zero return code failure tracking, and logs export (`get_session_log_export`).
  - `telegram_bot.py`: Telegram remote control daemon with whitelist security, persistent Quick-Action Keyboard, interactive prompt keypad, callback query message resolvers, `/sessions`, `/history`, `/logs`, `/controls`, `/screenshot`.
  - `formatter.py`: Converts Markdown output to native Telegram HTML.
- `setup/` - Automated setup & guides:
  - `install.bat`: 1-click Windows installer (detects/installs Python via winget if missing, creates `.venv`, installs requirements, runs test suite, copies `.env.example`, pauses at end).
  - `setup_guide.md`: Complete step-by-step documentation for users cloning the repo.
- `tests/` - Unit tests (26 passed):
  - `test_screenshot.py`: Tests screenshot capture and terminal snapshot rendering.
  - `test_stream_manager.py`: Tests ANSI stripping, terminal windowing, 500ms buffer accumulation, ~1.0s periodic edits, completion events, error/cancel events.
  - `test_runner.py`: Tests runner initialization, workspace switching, session resets, conversation discovery, turn extraction, and log export.
  - `test_formatter.py`: Tests Markdown-to-HTML conversion.
  - `test_watcher.py`: Tests live transcript change detection, tool call extraction with HTML entity escaping, and dispatching.
  - `test_injector.py`: Tests process detection, alphanumeric/symbol/space key event records, special keys (Yes/No/Select/Arrows/Ctrl+C), scan codes, and injection safety fallback.
- `.tmp/` - Temporary files and process run logs.
- `.env` - Environment secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`).
- `run_bot.bat` - Windows single-click launcher.
- `install.bat` - Root wrapper for `setup/install.bat`.

## Quick-Action Bottom Bar Keyboard
- Row 1: `[ 📊 Status ]` `[ 📜 Sessions ]` `[ 📸 Screenshot ]`
- Row 2: `[ 📁 PWD ]` `[ 🎮 Controls ]` `[ 🛑 Stop Task ]`

## Interactive Keypad Controls
- `[ ✅ Yes (Y) ]` `[ ❌ No (N) ]` `[ ⏎ Enter ]`
- `[ ⬆️ Up ]` `[ ⬇️ Down ]` `[ ␣ Space ]`
- `[ 1️⃣ Select 1 ]` `[ 2️⃣ Select 2 ]` `[ 3️⃣ Select 3 ]`
- `[ 🛑 Ctrl+C ]` `[ ⌫ Backspace ]` `[ 📸 Screenshot ]`

## Status & Next Steps
- Status: Full codebase bug audit and fixes applied (callback query message resolution, HTML escaping in tool bullets, non-zero return code detection, auto-tracking initial watcher fallback). 26 unit tests passing (100% success). Daemon active.
- Last updated: 2026-11-15.
