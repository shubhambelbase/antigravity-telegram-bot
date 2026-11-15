@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo   Antigravity Telegram Bot - Setup & Installer
echo ====================================================
echo.

cd /d "%~dp0\.."

:: 1. Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10 or higher from https://www.python.org/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Detected Python %PY_VER%

:: 2. Create Virtual Environment
if not exist ".venv" (
    echo [*] Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists (.venv).
)

:: 3. Install Dependencies
echo [*] Installing required packages...
call .venv\Scripts\activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies from requirements.txt.
    pause
    exit /b 1
)
echo [OK] Dependencies installed successfully.

:: 4. Verify Tests
echo [*] Running self-test suite...
python -m pytest tests/ --quiet
if errorlevel 1 (
    echo [WARNING] Some unit tests had issues. Check logs if needed.
) else (
    echo [OK] All self-tests passed successfully!
)

:: 5. Setup .env file
if not exist ".env" (
    echo [*] Creating .env from .env.example...
    copy .env.example .env >nul
    echo.
    echo ====================================================
    echo   [ACTION REQUIRED]
    echo   A new .env file has been created.
    echo   Please open .env and enter your TELEGRAM_BOT_TOKEN
    echo   obtained from @BotFather.
    echo ====================================================
) else (
    echo [OK] Configuration file .env already exists.
)

echo.
echo ====================================================
echo   Setup Complete!
echo   To launch your bot, double-click: run_bot.bat
echo ====================================================
echo.
pause
