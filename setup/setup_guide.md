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
* **Auto-healing launcher:** If a user double-clicks `run_bot.bat` before installing, it automatically runs the installer first.

---

## Prerequisites (Handled Automatically by Installer)

1. **Operating System:** Windows 10 or 11 (64-bit).
2. **Python:** Version 3.10 or higher *(automatically installed by `install.bat` if missing)*.
3. **Google Antigravity CLI (`agy`):** Installed and authenticated on your machine.
   - Run `agy --help` in PowerShell or CMD to verify.
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

## Step 2: Clone or Download the Project

Clone or extract the repository into any directory:
```powershell
git clone https://github.com/your-username/antigravity-telegram-bot.git
cd antigravity-telegram-bot
```

---

## Step 3: Run the Automated 1-Click Installer

Double-click **`install.bat`** in the project root (or run `setup\install.bat`):
```powershell
install.bat
```

This automated installer will:
1. Verify Python 3.10+ (or install Python 3.12 automatically via winget if missing).
2. Create an isolated virtual environment (`.venv`).
3. Upgrade pip and install all dependencies (`python-telegram-bot`, `pillow`, `psutil`, `pytest`, `python-dotenv`).
4. Execute the automated verification suite (**39 unit tests**) to verify system compatibility.
5. Create your `.env` configuration file from `.env.example`.

---

## Step 4: Configure Your `.env` File

Open the `.env` file in Notepad:
```env
# 1. Paste your bot token from @BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ

# 2. Leave this blank for now! (Auto-pairing will set this in Step 5)
ALLOWED_TELEGRAM_USER_IDS=

# 3. Default workspace folder for agent tasks
DEFAULT_WORKSPACE=.

# 4. Path to agy.exe (leave blank for automatic auto-detection)
AGY_PATH=
```

---

## Step 5: Launch the Bot & Pair Your Account

1. Double-click **`run_bot.bat`** in the project root.
2. Open Telegram on your phone or PC and open your bot.
3. Click **Start** (or send `/start`).
4. The bot will detect that it is unbonded and enter **Setup Mode**:
   ```text
   🔒 Antigravity Controller (Setup Mode)
   Your Telegram User ID is: 123456789
   To pair and lock it to your account, send:
   /claim 123456789
   ```
5. Send `/claim <YOUR_USER_ID>`.
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

### Option 1: 1-Click Batch Script
- **To Enable:** Double-click `setup\enable_autostart.bat`.
- **To Disable:** Double-click `setup\disable_autostart.bat`.

### Option 2: Directly from Telegram
- Send `/autostart` to toggle auto-start on/off.
- Or tap `[ 🚀 Enable Auto-Start ]` on your `/status` card.

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

---

## Pushing to GitHub (`setup/push_to_github.bat`)

To push this project to your GitHub account:
1. Double-click `setup\push_to_github.bat`.
2. The script will:
   - Run a secret audit to ensure `.env` and credentials are never pushed.
   - Run the 46 automated unit tests.
   - If GitHub CLI (`gh`) is logged in, offer to automatically create a repository for you (public or private).
   - If entering a URL manually, connect remote `origin` and push branch `main`.
