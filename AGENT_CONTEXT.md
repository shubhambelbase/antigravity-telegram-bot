# Project Context: Antigravity Telegram Bot

## Overview
A lightweight, reliable, autonomous Telegram bot controller for Google Antigravity CLI (`agy`). Enables remote execution of coding tasks, project navigation, conversation history resumption with 1-click inline buttons, rich Markdown formatting, a persistent Quick-Action Keyboard (Bottom Bar) for 1-tap commands, and a Hybrid Message Editing + Event-Based Streaming mechanism that turns Telegram into a remote terminal without flooding the chat.

## Stack & Environment
- **OS**: Windows
- **Python**: 3.14 (.venv in project root)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pillow` (v13+), `pytest`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe`)

## Architecture & Layout
- `directives/` - Standard Operating Procedures:
  - `antigravity_telegram_bridge.md`: Execution rules, timeouts, safety protocols.
- `execution/` - Core Python services:
  - `screenshot.py`: Desktop screen capture utility (PIL ImageGrab / PowerShell) and high-fidelity dark-mode terminal window snapshot renderer.
  - `stream_manager.py`: Hybrid Message Editing + Event-Based Streaming manager. Maintains persistent live terminal message with 500ms debounce buffer, ~1.0s `editMessageText` updates, and separate event notifications for completions/errors.
  - `console_injector.py`: Win32 `AttachConsole`, `VkKeyScanW`, `MapVirtualKeyW`, and `WriteConsoleInputW` injector typing prompts into the active desktop terminal with hardware scan codes, shift state, character pacing, and window focus.
  - `transcript_watcher.py`: Real-time asynchronous transcript observer tailing `transcript.jsonl` to detect desktop PC interactions, extracting tool calls and thinking traces, and pushing them to Telegram.
  - `agy_runner.py`: Subprocess manager wrapping `agy -p` with conversation resumption, session discovery (`get_recent_conversations`), attach controls, and abort handling.
  - `telegram_bot.py`: Telegram polling bot with user whitelist security, persistent Quick-Action Keyboard, hybrid stream integration, inline buttons, `/sessions`, `/attach`, `/screenshot`, and PID file single-instance lock.
  - `formatter.py`: Converts Markdown output to native Telegram HTML.
- `setup/` - Automated setup & guides:
  - `install.bat`: 1-click Windows installer (detects/installs Python via winget if missing, creates `.venv`, installs requirements, runs test suite, copies `.env.example`, pauses at end).
  - `setup_guide.md`: Complete step-by-step documentation for users cloning the repo.
- `tests/` - Unit tests (24 passed):
  - `test_screenshot.py`: Tests screenshot capture and terminal snapshot rendering.
  - `test_stream_manager.py`: Tests ANSI stripping, terminal windowing, 500ms buffer accumulation, ~1.0s periodic edits, completion events, error/cancel events.
  - `test_runner.py`: Tests runner initialization, workspace switching, session resets, and conversation discovery.
  - `test_formatter.py`: Tests Markdown-to-HTML conversion.
  - `test_watcher.py`: Tests live transcript change detection, tool call extraction, and dispatching.
  - `test_injector.py`: Tests process detection, alphanumeric/symbol/space key event records, scan codes, and injection safety fallback.
- `.tmp/` - Temporary files and process run logs.
- `.env` - Environment secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`).
- `run_bot.bat` - Windows single-click launcher.
- `install.bat` - Root wrapper for `setup/install.bat`.

## Quick-Action Bottom Bar Keyboard
- Row 1: `[ 📊 Status ]` `[ 📜 Sessions ]` `[ 📸 Screenshot ]`
- Row 2: `[ 📁 PWD ]` `[ 🔄 New Turn ]` `[ 🛑 Stop Task ]`

## Status & Next Steps
- Status: Console injector upgraded with hardware scan codes, pacing, and automatic headless fallback. All 24 unit tests passing (100% success). Background polling service operational.
- Last updated: 2026-11-15.
