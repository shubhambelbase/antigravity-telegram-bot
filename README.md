<div align="center">

# 🤖 Antigravity Telegram Controller

**Drive, monitor, and interact with the Google Antigravity CLI (`agy`) directly from Telegram.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D6.svg)](https://microsoft.com/windows)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-2CA5E0.svg?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

*Direct PC screen typing • Live tool execution logs • 1-click session resumption • Human-in-the-loop pairing security*

</div>

---

## 🌟 Highlights

- 📺 **Direct PC Screen Keystroke Injection**: When your Antigravity terminal is open on your desktop, prompts sent from Telegram physically type out on your monitor and run right before your eyes!
- 🔄 **Bidirectional Real-Time Mirroring**: Anything you type in your PC terminal mirrors to Telegram in real-time. Anything you send from Telegram mirrors to your PC.
- 📋 **Live Tool Execution Logs**: See the exact steps Antigravity takes live on Telegram (`○ Thought`, `● Ran command`, `● Edited file`, `● Created file`, `● Read file`).
- 🔘 **1-Click Session Switcher**: View past Antigravity conversations with `/sessions` and attach to any session with full history via interactive inline buttons.
- 🔒 **Biometric / Numerical User ID Security**: Whitelist-based authentication locks the bot strictly to your Telegram account. Unauthorized strangers are instantly blocked.
- ⚡ **Autonomous & Headless Ready**: If you step away and close your desktop terminal, the bot automatically falls back to headless background execution so you can code from anywhere.
- 🛡️ **FloodWait Rate-Limit Safe**: Debounced message streaming ensures Telegram API limits (`429 Too Many Requests`) are never breached.

---

## 🏗️ Architecture

```
            Telegram User (Phone / Desktop)
                           │
                           ▼  (Long Polling)
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Controller Daemon                   │
│  ├── 🛡️ Whitelist Auth Guard (Rejects unauthorized IDs)      │
│  ├── 🔘 Inline Keyboard Session Manager (/sessions, /attach)│
│  ├── ⏱️ Rate-Limited Streamer (Debounced edit updates)       │
│  └── 🔍 Real-Time Transcript Watcher (transcript.jsonl)     │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
       (Active Terminal Open)          (Terminal Closed / Away)
               ▼                               ▼
┌───────────────────────────────┐  ┌───────────────────────────┐
│ Win32 Keystroke Injector      │  │ Headless Runner           │
│ (AttachConsole + CONIN$)      │  │ (agy -p --continue)       │
│ Types & runs directly on your │  │ Headless autonomous       │
│ visible PC terminal screen!   │  │ execution in workspace    │
└───────────────────────────────┘  └───────────────────────────┘
```

---

## 🚀 Quickstart (3 Minutes)

### 1. Prerequisites
- **Windows 10 / 11 (64-bit)**
- **Python 3.10+** (Ensure *"Add to PATH"* is checked during installation)
- **Google Antigravity CLI (`agy`)** installed and authenticated

### 2. Get a Bot Token
1. Open Telegram and search for **`@BotFather`**.
2. Send `/newbot`, choose a name and username.
3. Copy the HTTP API Token provided.

### 3. Install
Clone the repository and run the automated installer:
```cmd
git clone https://github.com/your-username/antigravity-telegram-bot.git
cd antigravity-telegram-bot
setup\install.bat
```
*(The installer sets up your `.venv`, installs requirements, runs 13 unit tests, and creates your `.env` configuration file).*

### 4. Configure & Launch
1. Open `.env` and paste your bot token:
   ```env
   TELEGRAM_BOT_TOKEN=your_token_here
   ```
2. Double-click **`run_bot.bat`**.
3. In Telegram, open your bot, send **`/start`**, and click the pairing command (e.g. `/claim <YOUR_ID>`).
4. You are ready! Send any coding prompt or command.

For full setup documentation, see [setup/setup_guide.md](setup/setup_guide.md).

---

## 🎮 Command Reference

| Command | Description |
| :--- | :--- |
| **`<any prompt>`** | Sends a task to Antigravity (types on your desktop terminal or runs headlessly). |
| **`/sessions`** | Lists recent conversations with 1-click interactive inline buttons. |
| **`/attach <1-5 or ID>`** | Attaches to any past conversation session with full history and context. |
| **`/status`** | Displays active session ID, desktop terminal connection, host CPU & RAM. |
| **`/cd <path>`** | Switches active workspace directory on your machine. |
| **`/pwd`** | Displays the current workspace folder path. |
| **`/new`** | Starts a clean conversation turn. |
| **`/stop` or `/cancel`** | Immediately terminates the currently executing agent turn. |

---

## 🔒 Security Model

- **Zero Hardcoded Secrets**: All tokens and IDs are stored in `.env` (gitignored).
- **Hard Whitelist**: Only the Telegram User ID you authorize during `/claim` can send instructions.
- **Outbound Long Polling**: The bot does not open incoming ports on your router or computer, eliminating external attack vectors.
- **Single-Instance Lock**: Protected by a PID lock file (`.bot.pid`) to prevent conflicting polling loops.

---

## 🧪 Testing

Run the full automated test suite anytime:
```cmd
python -m pytest tests/
```
Output:
```text
tests\test_formatter.py ...    [ 23%]
tests\test_injector.py ..      [ 38%]
tests\test_runner.py ....      [ 69%]
tests\test_watcher.py ....     [100%]
============================= 13 passed in 0.3s =============================
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
