# Antigravity Telegram Bot — Setup & User Guide

A step-by-step guide to installing, configuring, and operating the autonomous **Antigravity Remote Control Center** for Windows.

---

## Key Features

* ⚡ **Live Hybrid Streaming:** Updates a persistent Telegram message every ~1.0s with buffered terminal output and delivers separate event notifications upon completion.
* 📊 **Adaptive Progress System:** Real-time visual progress supporting:
  - **Mode A (Indeterminate):** Animated activity indicator for planning and exploring.
  - **Mode B (Activity-based):** Weighted work unit progress bar (planning 10, exploring 10, editing 30, testing 25, fixing 15, verification 10).
  - **Mode C (Determinate):** Measured task units (e.g., `16/20 tests completed = 80%`).
* 📁 **Mobile Workspace Browser:** 1-tap folder navigation, drive switcher (`C:\`, `D:\`, `E:\`), recent workspaces list, and relative `cd` navigation.
* 🎮 **Interactive Hardware Keypad:** Instant scan-code keystroke injection for interactive prompts (`Yes / No / Select 1, 2, 3 / Arrows / Ctrl+C`).
* 📸 **WinSta0 Desktop Capture:** Live physical desktop screenshots captured directly from background daemon sessions with blank/transparency validation.
* 📄 **Zero-Loss Document Delivery:** Automatically packages and delivers full untruncated responses as `.txt` files whenever outputs exceed Telegram's 4,096-character limit.
* 🔒 **Zero-Config Whitelist Pairing:** Single-click account pairing via `/claim` with strict user whitelist security.

---

## Zero-Setup Guarantee for Any Fresh Windows PC

Anyone can download or clone this project onto a brand-new Windows PC with **zero manual configuration**:
* **No Python pre-installation required:** If Python 3.10+ is missing, the installer automatically downloads and installs the official Python 3.12 runtime.
* **No system PATH pollution:** Dependencies are installed into an isolated local `.venv` inside the project folder.
* **Silent background startup:** Supports windowless `pythonw.exe` execution via `setup/start_bot_silent.vbs` and `/autostart`.

---

## Prerequisites

1. **Operating System:** Windows 10 or 11 (64-bit).
2. **Python:** Version 3.10 or higher (`python --version`).
3. **Google Antigravity CLI (`agy`):** Installed and authenticated on your machine.
   - Run `agy --help` in PowerShell to verify.
4. **Telegram Account:** Any official Telegram mobile or desktop client.

---

## Step 1: Create Your Telegram Bot

1. Open Telegram and search for the official **`@BotFather`**.
2. Send `/newbot`.
3. Choose a display name (e.g., `My Antigravity Controller`).
4. Choose a unique username ending in `bot` (e.g., `my_agy_remote_bot`).
5. `@BotFather` will reply with your **HTTP API Token** (e.g., `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).
6. Copy this token. **Keep it confidential.**

---

## Step 2: Clone & Install in PowerShell

```powershell
git clone https://github.com/shubhambelbase/antigravity-telegram-bot.git
cd antigravity-telegram-bot

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Verify your environment with pytest:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

---

## Step 3: Configure Your `.env` File

Open `.env` in Notepad (`notepad .env`):
```env
# 1. Paste your bot token from @BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ

# 2. Leave this blank for now! (Auto-pairing will set this in Step 4)
ALLOWED_TELEGRAM_USER_IDS=

# 3. Default workspace folder for agent tasks
DEFAULT_WORKSPACE=.

# 4. Path to agy.exe (leave blank for automatic auto-detection)
AGY_PATH=
```

---

## Step 4: Launch the Bot & Pair Your Account

1. Run the bot in PowerShell:
   ```powershell
   .\.venv\Scripts\python.exe -m execution.telegram_bot
   ```
   *(Or launch silently without a console window: `wscript.exe .\setup\start_bot_silent.vbs`)*
2. Open Telegram on your phone or PC and open your bot.
3. Click **Start** (or send `/start`).
4. The bot will enter **Setup Mode** and generate a local 6-digit pairing PIN (printed to the bot console, `logs/bot.log`, and `.tmp/pairing_code.txt`):
   ```text
   🔒 Antigravity Controller (Setup Mode)
   Your Telegram User ID is: 123456789
   This bot is unclaimed. Check your local PC console, logs/bot.log, or .tmp/pairing_code.txt for the 6-digit pairing PIN, then send:
   /claim <PIN>
   ```
5. Send `/claim <PIN>` from your Telegram client.
6. The bot automatically updates `.env` with your ID and locks down access so **only you** can control your machine.

---

## Quick-Action Bottom Bar Keyboard

The persistent bottom bar gives you instant 1-tap access on mobile:

| Button | Action |
| :--- | :--- |
| **`[ 📊 Status ]`** | Live CLI connection, host CPU & RAM, active session ID, and workspace. |
| **`[ 📜 Sessions ]`** | Lists recent sessions with 1-click inline buttons to resume history. |
| **`[ 📸 Screenshot ]`** | Captures a live snapshot of your desktop screen or terminal window. |
| **`[ 📁 PWD ]`** | Opens the visual Workspace Browser with folder buttons, drives, and recent paths. |
| **`[ 🎮 Controls ]`** | Displays the interactive hardware keypad for prompt responses. |
| **`[ 🛑 Stop Task ]`** | Immediately terminates the running task (Ctrl+C / Process Kill). |

---

## Interactive Prompts Keypad

When an interactive CLI prompt appears (e.g. `Do you want to proceed? [y/N]`):

* Tap **`[ 🎮 Controls ]`** to open the interactive keypad:
  - `[ ✅ Yes (Y) ]` `[ ❌ No (N) ]` `[ ⏎ Enter ]`
  - `[ ⬆️ Up ]` `[ ⬇️ Down ]` `[ ␣ Space ]`
  - `[ 1️⃣ Select 1 ]` `[ 2️⃣ Select 2 ]` `[ 3️⃣ Select 3 ]`
  - `[ 🛑 Ctrl+C ]` `[ ⌫ Backspace ]` `[ 📸 Screenshot ]`

---

## Workspace Navigation & Management

You can change and manage workspaces directly in Telegram:

1. **Visual Folder Browser:** Tap `[ 📁 PWD ]` or send `/pwd` to navigate up/down folders and switch drives with one touch.
2. **Path Navigation:** Send `/cd <path>` or `cd <path>`:
   - `cd ..` *(navigates to parent directory)*
   - `cd execution` *(navigates into subfolder)*
   - `/cd E:\my_other_project` *(switches to absolute path)*
3. **Directory Creation:** Send `/mkdir <folder_name>` to create a directory and switch into it automatically.

---

## Command Reference

| Command | Description |
| :--- | :--- |
| **`<any text>`** | Types command directly into active desktop terminal or executes headlessly. |
| **`/start`** | Displays the controller dashboard and help overview. |
| **`/status`** | Host CPU/RAM, connection state, and active workspace. |
| **`/pwd` or `/workspace`** | Opens the interactive visual workspace browser. |
| **`/cd <path>`** | Changes the active workspace directory. |
| **`/mkdir <path>`** | Creates a new directory and sets it as the active workspace. |
| **`/sessions`** | Displays recent Antigravity sessions with 1-click attach buttons. |
| **`/attach <id>`** | Resumes a previous conversation with full session history. |
| **`/history [limit]`** | Displays the last conversation turns (User vs Agent). |
| **`/logs [id]`** | Exports and downloads the complete session execution log. |
| **`/screenshot`** | Captures live Windows desktop screen. |
| **`/controls`** | Opens interactive hardware keypad. |
| **`/sync`** | Toggles live PC terminal mirroring on/off (Silent Mode). |
| **`/autostart`** | Toggles Windows auto-start on laptop boot. |
| **`/new`** | Starts a fresh conversation turn in the active workspace. |
| **`/stop` or `/cancel`** | Kills the currently executing task immediately. |

---

## Windows Auto-Start on Laptop Boot

The bot can automatically launch in the background whenever you boot or log in to your Windows laptop:

### Option 1: Directly from Telegram
- Send `/autostart` to toggle auto-start on/off.
- Or tap `[ 🚀 Enable Auto-Start ]` on your `/status` card.

### Option 2: PowerShell
```powershell
.\.venv\Scripts\python.exe -c "from execution.autostart import enable_autostart; enable_autostart()"
```

### How It Works Under the Hood
1. A shortcut is registered in your personal Windows Startup directory (`shell:startup`).
2. On login, Windows launches `start_bot_silent.vbs` via `wscript.exe`.
3. The VBScript invokes Python using `.venv\Scripts\pythonw.exe`, running the bot 100% silently in the background with zero terminal windows or taskbar clutter.
4. Single-instance locking (`.bot.pid`) prevents duplicate processes.

---

## Security Architecture

* **Zero Open Ports:** Uses Telegram Long Polling (`getUpdates`); no open inbound ports or port-forwarding required.
* **Whitelist Enforcement:** Every update is checked against `ALLOWED_TELEGRAM_USER_IDS`. Unauthorized requests are discarded and logged.
* **Secret Protection:** `.env` and `.bot.pid` are strictly excluded from version control via `.gitignore`.
