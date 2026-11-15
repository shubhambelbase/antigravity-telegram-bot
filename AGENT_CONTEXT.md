# Project Context: Antigravity Telegram Bot

## Overview
A lightweight, reliable, autonomous Telegram remote control center for Google Antigravity CLI (`agy`). Features real-time CLI connection detection, normal command execution, interactive prompts (Yes / No / Select / Navigation keys), live hybrid streaming output with 1-second edits, Adaptive Progress System (Indeterminate, Activity-based, and Determinate states), Live PC Sync mute/pause controls (`/sync`, `/mute`), desktop screen snapshotting with WinSta0 desktop attachment, interactive Telegram workspace browser (`/cd`, `/pwd`, `/mkdir`), and full session history / logs inspection.

## Stack & Environment
- **OS**: Windows
- **Python**: 3.14 (.venv in project root)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pillow` (v13+), `pytest`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe`)

## Architecture & Layout
- `directives/` - Standard Operating Procedures:
  - `antigravity_telegram_bridge.md`: Execution rules, timeouts, safety protocols.
- `execution/` - Core Python services:
  - `progress_tracker.py`: Adaptive Progress System supporting Mode A (Indeterminate spinner for thinking/planning), Mode B (Activity-based weighted progress: planning 10, exploring 10, editing 30, testing 25, fixing 15, verification 10), and Mode C (Determinate measured progress e.g. 16/20 tests). Ensures non-decreasing monotonicity and cap rules.
  - `console_injector.py`: Win32 `AttachConsole`, `VkKeyScanW`, `MapVirtualKeyW`, and `WriteConsoleInputW` injector typing normal prompts and interactive keys (Yes/No/Select/Arrows/Ctrl+C).
  - `screenshot.py`: Desktop screen capture utility (WinSta0 / desktop attachment, PIL ImageGrab, Win32 GDI BitBlt) with blank/transparency validation (`is_blank_or_invalid_image`) and high-fidelity dark-mode terminal window snapshot renderer fallback.
  - `stream_manager.py`: Hybrid Message Editing + Event-Based Streaming manager. Embeds the Adaptive Progress Dashboard into the persistent live terminal message with 500ms debounce buffer, ~1.0s `editMessageText` updates, and separate event notifications for completions/errors.
  - `transcript_watcher.py`: Real-time asynchronous transcript observer tailing `transcript.jsonl` with safe HTML entity escaping, auto-detecting latest sessions, extracting tool calls/thoughts, and pausable live sync mirror (`pause()`/`resume()`).
  - `agy_runner.py`: Subprocess manager wrapping `agy -p` with conversation resumption, session discovery (`get_recent_conversations`), workspace resolution, subdirectory listing, parent tracking, system drive discovery, and recent workspaces history.
  - `telegram_bot.py`: Telegram remote control daemon with whitelist security, persistent Quick-Action Keyboard, interactive prompt keypad, workspace browser (`build_workspace_view`, `/cd`, `/pwd`, `/mkdir`, `ws:*` callback handlers), live sync control (`/sync`, `/mute`, `sync:toggle`), `/sessions`, `/history`, `/logs`, `/controls`, `/screenshot`.
  - `formatter.py`: Converts Markdown output to native Telegram HTML.
- `setup/` - Automated setup & guides:
  - `install.bat`: 1-click Windows installer (detects/installs Python via winget if missing, creates `.venv`, installs requirements including pytest, runs 40 verification tests with 100% success, copies `.env.example`, pauses at end).
  - `setup_guide.md`: Comprehensive step-by-step setup, configuration, interactive keypad, mobile workspace browser, and command reference guide.
- `tests/` - Unit tests (40 passed):
  - `test_watcher.py`: Tests live transcript change detection, tool call extraction with HTML entity escaping, and pause/resume live sync toggle.
  - `test_progress_tracker.py`: Tests Mode A (indeterminate), Mode B (activity-based), Mode C (determinate), monotonic non-decreasing progress, 95% cap rule, and pytest line integration.
  - `test_workspace.py`: Tests interactive workspace browser cards, child folder buttons, and system drive selection menus.
  - `test_screenshot.py`: Tests screenshot capture, WinSta0 attachment, blank/transparent validation, and terminal snapshot rendering.
  - `test_stream_manager.py`: Tests ANSI stripping, terminal windowing, 500ms buffer accumulation, ~1.0s periodic edits, completion events, error/cancel events.
  - `test_runner.py`: Tests runner initialization, relative/absolute workspace switching, folder creation, subdirectory inspection, parent directory retrieval, and session logs export.
  - `test_formatter.py`: Tests Markdown-to-HTML conversion.
  - `test_injector.py`: Tests process detection, alphanumeric/symbol/space key event records, special keys (Yes/No/Select/Arrows/Ctrl+C), scan codes, and injection safety fallback.
- `.tmp/` - Temporary files, recent workspaces ledger (`recent_workspaces.json`), and process run logs.
- `.env` - Environment secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`).
- `run_bot.bat` - Windows single-click launcher with auto-healing installer fallback.
- `install.bat` - Root wrapper for `setup/install.bat`.

## Quick-Action Bottom Bar Keyboard
- Row 1: `[ 📊 Status ]` `[ 📜 Sessions ]` `[ 📸 Screenshot ]`
- Row 2: `[ 📁 PWD ]` `[ 🎮 Controls ]` `[ 🛑 Stop Task ]`

## Interactive Keypad Controls
- `[ ✅ Yes (Y) ]` `[ ❌ No (N) ]` `[ ⏎ Enter ]`
- `[ ⬆️ Up ]` `[ ⬇️ Down ]` `[ ␣ Space ]`
- `[ 1️⃣ Select 1 ]` `[ 2️⃣ Select 2 ]` `[ 3️⃣ Select 3 ]`
- `[ 🛑 Ctrl+C ]` `[ ⌫ Backspace ]` `[ 📸 Screenshot ]`

## Live Sync Control
- `/sync` or `/sync off` or `/mute`: Pauses live PC terminal mirroring (Silent Mode).
- `/sync on` or `/unmute`: Resumes live PC terminal mirroring.
- `[ 🔕 Mute Live Sync ]` / `[ 🔔 Enable Live Sync ]`: 1-tap inline toggle in `/status`.

## Workspace Commands & Navigation
- `[ 📁 PWD ]` or `/pwd` / `/workspace`: Opens interactive folder browser with parent, child folders, drives, and recent workspaces.
- `/cd <path>` or `cd <path>`: Switches workspace (supports relative `..`, `subfolder`, or absolute `E:\project`).
- `/mkdir <path>`: Creates a directory and immediately switches workspace into it.

## Status & Next Steps
- Status: Live Sync control (Mute/Pause/Resume) implemented. All 40 unit tests passing (100% success). Daemon active and polling.
- Last updated: 2026-11-15.
