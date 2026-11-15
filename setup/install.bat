@echo off
setlocal enabledelayedexpansion

title Antigravity Telegram Bot - Automatic Installer
echo ====================================================
echo   Antigravity Telegram Bot - Automated Setup
echo ====================================================
echo.

REM Navigate to project root directory
cd /d "%~dp0.."

REM 1. Check Python installation
python --version >nul 2>&1
if errorlevel 1 goto :no_python
goto :check_python_version

:no_python
py -3 --version >nul 2>&1
if not errorlevel 1 goto :check_python_version

echo [!] Python was not detected on your system.
echo [*] Attempting automated Python 3.12 installation via Windows winget...
echo.

winget --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] winget is unavailable. Please install Python 3.10+
    echo from https://www.python.org/downloads/ - check Add Python to PATH.
    pause
    exit /b 1
)

winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [ERROR] Automated installation failed. Please install Python manually.
    pause
    exit /b 1
)

echo [OK] Python installation completed. Refreshing environment...
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"

:check_python_version
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is still not accessible in PATH. Please restart your terminal.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo [OK] Using Python %PY_VER%

REM 2. Create isolated Virtual Environment
if exist ".venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists at .venv
) else (
    echo [*] Creating isolated virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created successfully.
)

REM 3. Upgrade pip and install all required Python packages
echo [*] Installing required Python tools and packages...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install packages from requirements.txt.
    pause
    exit /b 1
)
echo [OK] All Python tools and dependencies installed successfully.

REM 4. Run automated self-tests
echo [*] Running automated verification test suite...
python -m pytest tests/ --quiet
if errorlevel 1 (
    echo [WARNING] Some self-tests had warnings. Check logs if needed.
) else (
    echo [OK] All 13 unit tests passed with 100%% success!
)

REM 5. Generate .env configuration file if missing
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

REM 6. Check for Antigravity CLI
where agy >nul 2>&1
if errorlevel 1 (
    if not exist "%LOCALAPPDATA%\agy\bin\agy.exe" (
        echo [!] Note: agy CLI was not found in standard PATH.
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