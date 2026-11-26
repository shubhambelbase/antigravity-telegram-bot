# Project Context: Antigravity Telegram Bot

## Overview
Autonomous Telegram remote control center for Google Antigravity CLI (`agy`) on Windows. Supports live desktop terminal keystroke injection (via isolated worker subprocess), `--output-format stream-json` headless execution, bidirectional `transcript.jsonl` mirroring (`/sync`, `/mute`), hybrid 1s terminal streaming with Adaptive Progress Dashboard, interactive keypad (`/controls`), desktop screen capture (`/screenshot`), workspace navigation (`/cd`, `/pwd`, `/mkdir`), and session switching (`/sessions`, `/attach`, `/history`, `/logs`).

## Stack & Environment
- **OS**: Windows 10 / 11
- **Python**: 3.11.9 (`.venv` in project root; `requires-python >= 3.10`)
- **Key Libraries**: `python-telegram-bot` (v22+), `python-dotenv`, `psutil`, `pillow`, `pytest`, `anyio`, `ctypes` (Win32 API)
- **CLI Binary**: `agy.exe` (`%LOCALAPPDATA%\agy\bin\agy.exe` or PATH)

## Architecture & Layout
- `pyproject.toml` - PEP 517/621 config with `antigravity-bot` entrypoint (`execution.telegram_bot:main`).
- `directives/antigravity_telegram_bridge.md` - Operational SOP, safety rules, and learnings.
- `execution/` - Core package:
  - `progress_tracker.py`: Mode A (Indeterminate shimmer), Mode B (weighted activity), Mode C (determinate tests) with monotonic progress and 95% cap.
  - `console_injector.py`: Isolated Win32 `AttachConsole` + `WriteConsoleInputW` worker (`--worker`) keeping parent console intact and shielding `CTRL_C_EVENT`; strict session/workspace PID matching (`presence/*.lock` & `conversations/*.db`).
  - `screenshot.py`: WinSta0/Desktop capture (with Win32 handle cleanup), PIL `ImageGrab`, GDI `BitBlt`, PowerShell fallback, and TrueType dark-mode terminal snapshot fallback.
  - `stream_manager.py`: Hybrid streaming with 500ms debounce, ~1s edits, skeleton idle timeout (45s), post-escape 3,900-char Telegram guard, entity-unescaped plain fallback, and retry with backoff.
  - `transcript_watcher.py`: Async `transcript.jsonl` tailer using per-conversation state (`_conv_states`) to prevent multi-session thrashing/rewinds, offloaded disk I/O, and `mark_conv_caught_up()`.
  - `autostart.py`: Windows Startup shortcut manager (`setup/start_bot_silent.vbs`) with PowerShell quote escaping.
  - `agy_runner.py`: Headless `agy -p --output-format stream-json` runner with NDJSON parsing, process-tree termination on cancel/timeout, tail-bounded transcript reads, and `commonpath` traversal guards.
  - `telegram_bot.py`: Telegram daemon with local 6-digit pairing PIN (`PAIRING_PIN`/`.tmp/pairing_code.txt`), whitelist auth, Win32 single-instance mutex + `.bot.pid`, state persistence (`.tmp/bot_state.json`), async `to_thread` offloading, deferred logging, and supervisor exponential-backoff loop.
  - `formatter.py`: Markdown-to-Telegram-HTML converter and secret redactor (Telegram tokens, `sk-...`, `gh*`/`github_pat_`, `AIza...`, AWS `AKIA...`, Bearer tokens).
- `setup/` - `install.bat`, `run_bot.bat`, `start_bot_silent.vbs`, `enable_autostart.bat`, `disable_autostart.bat`, `push_to_github.bat`, `setup_guide.md`.
- `run.bat` - Root Windows launcher with auto-install and Python-verified PID conflict resolver.
- `tests/` - 11 test modules (`test_autostart.py`, `test_formatter.py`, `test_injector.py`, `test_progress_tracker.py`, `test_runner.py`, `test_screenshot.py`, `test_stream_manager.py`, `test_supervisor.py`, `test_telegram_bot.py`, `test_watcher.py`, `test_workspace.py`).
- `.tmp/` - Runtime intermediates (`recent_workspaces.json`, `bot_state.json`, `pairing_code.txt`, `diag.py`).
- `.env` - Runtime secrets (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_IDS`, `DEFAULT_WORKSPACE`, `AGY_PATH`, optional `PAIRING_PIN`, `AGY_MODE`, `AGY_MODEL`, `AGY_SKIP_PERMISSIONS`).

## Commands & Controls
- **Quick Bar**: `[ 📊 Status ]` `[ 📜 Sessions ]` `[ 📸 Screenshot ]` / `[ 📁 PWD ]` `[ 🎮 Controls ]` `[ 🛑 Stop Task ]`
- **Keypad (`key:*`)**: Yes/No/Enter, Up/Down/Space, Select 1–3, Ctrl+C (with busy confirmation), Backspace, Screenshot.
- **Session & Sync**: `/sessions`, `/attach`, `/history`, `/logs`, `/new`, `/stop`, `/sync`, `/mute`, `/unmute`, `/autostart`.
- **Workspace**: `/pwd`, `/workspace`, `/cd <path>`, `/mkdir <path>` (hashed callback tokens `ws:sub:<hash>` / `ws:rec:<hash>`).

## Security & Reliability Rules
- **Auth & Pairing**: Unclaimed setup requires a local 6-digit pairing PIN before `/claim <PIN>` writes `ALLOWED_TELEGRAM_USER_IDS` atomically to `.env`.
- **Injection Safety**: Never hijacks another workspace's or conversation's terminal; runs `AttachConsole` in a subprocess worker.
- **Test Isolation**: Logging initializes in `main()` (not at import time); `check_single_instance()` skips the global Win32 mutex when `PID_FILE` is patched in tests.
- **Run Tests**: `.venv\Scripts\python.exe -m pytest -v`

## Status & Next Steps
- **Status**: Full audit remediation completed (isolated console worker, strict workspace/session targeting, per-conversation `TranscriptWatcher` cursors, `stream-json` headless runner with process-tree kill, 4,096-char streaming/log guards, retry/backoff delivery, Win32 handle cleanup, pairing PIN, state persistence, deferred logging, `to_thread` offloading). `76/76` tests passing. Daemon not running (`python -m execution.telegram_bot` or `run.bat` to start).
- **Last updated**: 2026-11-25.
