@echo off
setlocal enabledelayedexpansion
title Antigravity Telegram Bot
cd /d "%~dp0.."

echo ====================================================
echo   Antigravity Telegram Bot Remote Control
echo ====================================================
echo.

REM If virtual environment does not exist, trigger installer
if not exist ".venv\Scripts\python.exe" (
    echo [!] First time setup required. Launching installer...
    echo.
    call "%~dp0install.bat"
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

REM Check if bot is already running
if exist ".bot.pid" (
    set /p EXISTING_PID=<.bot.pid
    powershell -Command "if (Get-Process -Id '!EXISTING_PID!' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo ====================================================
        echo [!] Bot is ALREADY RUNNING in background (PID: !EXISTING_PID!).
        echo ====================================================
        echo.
        echo Select an option:
        echo   [1] Stop background instance and run live in this window (Default)
        echo   [2] Leave background instance running and exit
        echo.
        set /p "USER_CHOICE=Enter choice [1/2, default 1]: "
        if "!USER_CHOICE!"=="" set "USER_CHOICE=1"
        if "!USER_CHOICE!"=="1" (
            echo [*] Stopping background process PID !EXISTING_PID!...
            taskkill /f /pid !EXISTING_PID! >nul 2>&1
            del /f /q ".bot.pid" >nul 2>&1
            timeout /t 1 /nobreak >nul
            echo [OK] Background process stopped. Starting in this window...
            echo.
        ) else (
            echo.
            echo [OK] Background bot remains active and polling.
            pause
            exit /b 0
        )
    ) else (
        del /f /q ".bot.pid" >nul 2>&1
    )
)

echo [*] Starting Antigravity Telegram Bot daemon...
echo [*] Press Ctrl+C at any time to stop.
echo.
".venv\Scripts\python.exe" -m execution.telegram_bot
set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo [*] Bot process exited cleanly.
) else (
    echo [!] Bot process terminated with exit code %EXIT_CODE%.
)
pause
