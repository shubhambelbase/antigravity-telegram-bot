@echo off
setlocal
title Antigravity Telegram Bot
cd /d "%~dp0"

echo ====================================================
echo   Antigravity Telegram Bot Remote Control
echo ====================================================
echo.

REM If virtual environment does not exist, trigger installer
if not exist ".venv\Scripts\python.exe" (
    echo [!] First time setup required. Launching installer...
    echo.
    call "%~dp0setup\install.bat"
    if not exist ".venv\Scripts\python.exe" (
        echo [ERROR] Installation was not completed. Exiting.
        pause
        exit /b 1
    )
)

REM Verify .env exists
if not exist ".env" (
    echo [*] Creating .env from template...
    copy .env.example .env >nul
    echo [ACTION REQUIRED] Please open .env and add your TELEGRAM_BOT_TOKEN before launching.
    notepad .env
    pause
    exit /b 1
)

echo [*] Starting Antigravity Telegram Bot daemon...
echo.
".venv\Scripts\python.exe" -m execution.telegram_bot
if errorlevel 1 (
    echo.
    echo [!] Bot process terminated with an error code.
    pause
)
