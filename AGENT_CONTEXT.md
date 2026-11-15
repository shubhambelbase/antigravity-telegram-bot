# Project Context: Antigravity Telegram Bot

## Overview
A lightweight, reliable, autonomous Telegram remote control center for Google Antigravity CLI (`agy`). Features real-time CLI connection detection, normal command execution, interactive prompts (Yes / No / Select / Navigation keys), live hybrid streaming output with 1-second edits, Adaptive Progress System (Indeterminate, Activity-based, and Determinate states), Live PC Sync mute/pause controls (`/sync`, `/mute`), desktop screen snapshotting with WinSta0 desktop attachment, interactive Telegram workspace browser (`/cd`, `/pwd`, `/mkdir`), and full session history / logs inspection.

## Stack & Environment
- **OS**: Windows
- **Python**: 3.14 (.venv in project root)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pillow` (v13+), `pytest`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe`)

## Architecture & Layout
- `pyproject.toml` - Standard PEP 517/621 Python package configuration with `antigravity-bot` CLI entrypoint (`execution.telegram_bot:main`).
- `directives/` - Standard Operating Procedures:
  - `antigravity_telegram_bridge.md`: Execution rules, timeouts, safety protocols.
- `execution/` - Core Python package:
  - `__init__.py`: Package marker and metadata.
  - `progress_tracker.py`: Adaptive Progress System supporting Mode A (Indeterminate spinner for thinking/planning), Mode B (Activity-based weighted progress: planning 10, exploring 10, editing 30, testing 25, fixing 15, verification 10), and Mode C (Determinate measured progress e.g. 16/20 tests). Ensures non-decreasing monotonicity, 95% cap rules, compact 3-item activity display, and clean tag-stripped bullets.
  - `console_injector.py`: Win32 `AttachConsole`, `VkKeyScanW`, `MapVirtualKeyW`, and `WriteConsoleInputW` injector typing normal prompts and interactive keys (Yes/No/Select/Arrows/Ctrl+C).
  - `screenshot.py`: Desktop screen capture utility (WinSta0 / desktop attachment, PIL ImageGrab, Win32 GDI BitBlt) with blank/transparency validation (`is_blank_or_invalid_image`) and high-fidelity dark-mode terminal window snapshot renderer fallback.
  - `stream_manager.py`: Hybrid Message Editing + Event-Based Streaming manager. Embeds the Adaptive Progress Dashboard into the persistent live terminal message with 500ms debounce buffer, ~1.0s `editMessageText` updates, consecutive line deduplication (`collapse_consecutive_lines`), compact sliding 8-line windowing (`format_terminal_window`), and separate event notifications for completions/errors.
  - `transcript_watcher.py`: Real-time asynchronous transcript observer tailing `transcript.jsonl` with safe HTML entity escaping, auto-detecting latest sessions, extracting tool calls/thoughts, and pausable live sync mirror (`pause()`/`resume()`).
  - `autostart.py`: Windows Startup folder shortcut manager (`enable_autostart`, `disable_autostart`, `is_autostart_enabled`) creating shortcuts for windowless background execution via `setup/start_bot_silent.vbs`.
  - `agy_runner.py`: Subprocess manager wrapping `agy -p` with conversation resumption, session discovery (`get_recent_conversations`), workspace resolution, subdirectory listing, parent tracking, system drive discovery, recent workspaces history, and transcript modification time resolver (`_get_conversation_mtime`) fixing Windows/NTFS folder timestamp inertia.
  - `telegram_bot.py`: Telegram remote control daemon with whitelist security, persistent Quick-Action Keyboard, interactive prompt keypad, workspace browser (`build_workspace_view`, `/cd`, `/pwd`, `/mkdir`, `ws:*` callback handlers), live sync control (`/sync`, `/mute`, `sync:toggle`), auto-start controls (`/autostart`, `autostart:toggle`), session reuse in `on_pc_user`, `/sessions`, `/history`, `/logs`, `/controls`, `/screenshot`.
  - `formatter.py`: Converts Markdown output to native Telegram HTML.
- `setup/` - Automated Windows setup, scripts & guides:
  - `push_to_github.bat`: Automated GitHub publisher with secret audit, test verification, gh CLI integration, and main branch push.
  - `run_bot.bat`: Windows single-click launcher with auto-healing installer fallback.
  - `start_bot_silent.vbs`: Windowless background launcher used by auto-start and startup shortcut.
  - `enable_autostart.bat` / `disable_autostart.bat`: 1-click Windows auto-start toggle scripts.
  - `install.bat`: 1-click Windows installer (detects/installs Python via winget if missing, creates `.venv`, installs requirements, runs 46 verification tests, copies `.env.example`, pauses at end).
  - `setup_guide.md`: Comprehensive step-by-step setup, configuration, interactive keypad, mobile workspace browser, and command reference guide.
- `tests/` - Unit tests (46 passed):
  - `test_autostart.py`: Tests Windows Startup folder resolution, shortcut creation, enable/disable operations.
  - `test_watcher.py`: Tests live transcript change detection, tool call extraction with HTML entity escaping, and pause/resume live sync toggle.
  - `test_progress_tracker.py`: Tests Mode A (indeterminate), Mode B (activity-based), Mode C (determinate), monotonic non-decreasing progress, 95% cap rule, pytest line integration, and markup stripping in activities.
  - `test_workspace.py`: Tests interactive workspace browser cards, child folder buttons, and system drive selection menus.
  - `test_screenshot.py`: Tests screenshot capture, WinSta0 attachment, blank/transparent validation, and terminal snapshot rendering.
  - `test_stream_manager.py`: Tests ANSI stripping, compact sliding terminal windowing, consecutive action deduplication/collapsing, 500ms buffer accumulation, ~1.0s periodic edits, completion events, error/cancel events.
  - `test_runner.py`: Tests runner initialization, relative/absolute workspace switching, folder creation, subdirectory inspection, parent directory retrieval, and session logs export.
  - `test_formatter.py`: Tests Markdown-to-HTML conversion.
  - `test_injector.py`: Tests process detection, alphanumeric/symbol/space key event records, special keys (Yes/No/Select/Arrows/Ctrl+C), scan codes, and injection safety fallback.
- `.tmp/` - Temporary files, recent workspaces ledger (`recent_workspaces.json`), and process run logs.
- `.env` - Environment secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`).
- `run.bat` - Root 1-click Windows launcher with auto-healing installer fallback.

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

## Auto-Start Control
- `/autostart` or `/autostart on` / `/autostart off`: Enables or disables background startup on Windows boot.
- `[ 🚀 Enable Auto-Start ]` / `[ 🛑 Disable Auto-Start ]`: 1-tap inline toggle in `/status`.
- Double-click `setup\enable_autostart.bat` or `setup\disable_autostart.bat`.

## Status & Next Steps
- Status: Windows Auto-Start configured and enabled on laptop startup (runs silently in background via start_bot_silent.vbs). All 46 unit tests passing (100% success). Daemon active and polling.
- Last updated: 2026-11-15.
