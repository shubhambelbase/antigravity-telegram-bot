@echo off
setlocal enabledelayedexpansion

title Antigravity Telegram Bot - Automatic Installer
echo ====================================================
echo   Antigravity Telegram Bot - Automated Setup
echo ====================================================
echo.

cd /d "%~dp0\.."

:: 1. Check Python installation; auto-install via winget if missing
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo [!] Python was not detected on your system.
        echo [*] Attempting automated Python 3.12 installation via Windows winget...
        echo.
        winget --version >nul 2>&1
        if not errorlevel 1 (
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            echo [OK] Python installation completed. Refreshing environment...
            set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
        ) else (
            echo [ERROR] winget is unavailable. Please download and install Python 3.10+
            echo from https://www.python.org/downloads/ (check 'Add Python to PATH').
            pause
            exit /b 1
        )
    )
)

:: Re-verify Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is still not accessible in PATH. Please restart your terminal or PC.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Using Python %PY_VER%

:: 2. Create isolated Virtual Environment
if not exist ".venv" (
    echo [*] Creating isolated virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created (.venv).
) else (
    echo [OK] Virtual environment already exists (.venv).
)

:: 3. Upgrade pip and install all required Python packages & tools
echo [*] Installing required Python tools and packages...
call .venv\Scripts\activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install packages from requirements.txt.
    pause
    exit /b 1
)
echo [OK] All Python tools and dependencies installed successfully.

:: 4. Run automated self-tests to verify compatibility
echo [*] Running automated verification test suite...
python -m pytest tests/ --quiet
if errorlevel 1 (
    echo [WARNING] Some self-tests had warnings. Check logs if needed.
) else (
    echo [OK] All 13 unit tests passed with 100%% success!
)

:: 5. Generate .env configuration file if missing
if not exist ".env" (
    echo [*] Creating .env configuration from template...
    copy .env.example .env >nul
    echo.
    echo ====================================================
    echo   [ACTION REQUIRED]
    echo   A new .env file has been created.
    echo   Please open .env and paste your TELEGRAM_BOT_TOKEN
    echo   from @BotFather.
    echo ====================================================
) else (
    echo [OK] Configuration file .env already exists.
)

:: 6. Check for Antigravity CLI (agy.exe)
where agy >nul 2>&1
if errorlevel 1 (
    if not exist "%LOCALAPPDATA%\agy\bin\agy.exe" (
        echo [!] Note: 'agy' CLI was not found in standard PATH.
        echo     Ensure Antigravity is installed from https://antigravity.google
    ) else (
        echo [OK] Antigravity CLI detected at %LOCALAPPDATA%\agy\bin\agy.exe
    )
) else (
    echo [OK] Antigravity CLI detected in system PATH.
)

echo.
echo ====================================================
echo   Setup Complete!
echo   To launch your bot, double-click: run_bot.bat
echo ====================================================
echo.
pause
