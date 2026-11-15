# Antigravity Telegram Bot — Setup & Deployment Guide

A step-by-step guide to installing, configuring, and deploying the autonomous **Antigravity Telegram Controller**.

---

## Prerequisites

1. **Operating System**: Windows 10 or 11 (64-bit).
2. **Python**: Version 3.10 or higher. [Download Python](https://www.python.org/downloads/) (Make sure to check *"Add python.exe to PATH"* during install).
3. **Google Antigravity CLI (`agy`)**: Installed and authenticated on your machine.
   - Run `agy --help` in your terminal to verify it is installed.
4. **Telegram Account**: Any official Telegram mobile or desktop client.

---

## Step 1: Create Your Telegram Bot

1. Open Telegram and search for the official **`@BotFather`**.
2. Send `/newbot`.
3. Give your bot a display name (e.g., `My Antigravity Assistant`).
4. Give your bot a unique username ending in `bot` (e.g., `my_agy_controller_bot`).
5. `@BotFather` will reply with your **HTTP API Token** (looks like: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).
6. Copy this token. **Do not share it with anyone.**

---

## Step 2: Clone or Download the Project

Clone the repository to any local folder on your computer:
```sh
git clone https://github.com/your-username/antigravity-telegram-bot.git
cd antigravity-telegram-bot
```

---

## Step 3: Run the Automatic Setup Script

Double-click `setup/install.bat` (or run it from terminal):
```sh
setup\install.bat
```

This script automatically:
- Checks your Python version.
- Creates an isolated virtual environment (`.venv`).
- Installs all dependencies (`python-telegram-bot`, `python-dotenv`, `psutil`, `pytest`).
- Runs the 13 automated unit tests to ensure your system is compatible.
- Creates your `.env` configuration file from `.env.example`.

---

## Step 4: Configure Your `.env` File

Open the newly generated `.env` file in Notepad or VS Code:

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

1. Double-click `run_bot.bat` in the project root.
2. Open Telegram on your phone or desktop and search for your bot username.
3. Click **Start** (or send `/start`).
4. Because the bot is brand new, it enters **Setup Mode** and displays your unique numerical User ID:
   ```text
   🔒 Antigravity Controller (Setup Mode)
   Your Telegram User ID is: 123456789
   To pair and lock it to your account, send:
   /claim 123456789
   ```
5. Send `/claim <YOUR_USER_ID>`.
6. The bot will automatically save your ID to `.env` and lock itself down so **only you** can control your PC!

---

## Step 6: Available Commands

| Command | Action |
| :--- | :--- |
| **`<any prompt>`** | Types the prompt directly into your active PC terminal screen (or executes headlessly if no terminal is open). |
| **`/sessions`** | Displays recent Antigravity sessions with 1-click inline buttons to resume history. |
| **`/attach <1-5 or ID>`** | Attaches to any past conversation session with full history. |
| **`/status`** | Displays host CPU/RAM, active session, and PC screen connection state. |
| **`/cd <path>`** | Switches active workspace directory on your machine. |
| **`/pwd`** | Displays current workspace directory. |
| **`/new`** | Starts a clean conversation turn. |
| **`/stop` or `/cancel`** | Kills the currently running agent task immediately. |

---

## Step 7 (Optional): Run 24/7 in Background on Windows

To have the bot start automatically on Windows boot without keeping a terminal open:

### Method A: Windows Task Scheduler (Recommended)
1. Press `Win + R`, type `taskschd.msc`, and press Enter.
2. Click **Create Basic Task...**
3. Name it: `Antigravity Telegram Bot`.
4. Trigger: **When I log on**.
5. Action: **Start a program**.
6. Program/script: Browse to `run_bot.bat`.
7. Finish. The bot will now run in the background whenever you log into Windows!

### Method B: Startup Folder
1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Right-click and create a **Shortcut** to `run_bot.bat`.
3. In shortcut properties, set **Run: Minimized**.

---

## Security Best Practices

- **Never commit `.env`**: Your `.env` contains your bot token and user whitelist. It is already included in `.gitignore`.
- **Zero Open Ports**: The bot connects outbound via Telegram Long Polling. You do not need to port forward or open firewall ports.
- **Whitelist Security**: Every incoming message is checked against `ALLOWED_TELEGRAM_USER_IDS`. Unauthorized users receive `⛔ Access Denied` and their messages are discarded.
