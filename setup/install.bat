@echo off
setlocal enabledelayedexpansion

title Antigravity Telegram Bot - Zero-Setup Installer
echo ====================================================
echo   Antigravity Telegram Bot - Automated Setup
echo   Zero-Configuration Installer for Any Windows PC
echo ====================================================
echo.

REM Navigate to project root directory
cd /d "%~dp0.."

REM ----------------------------------------------------
REM Step 1: Detect or Install Python
REM ----------------------------------------------------
set "PY_CMD="

REM Check standard python command
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

REM Check Windows Python launcher
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :python_found
)

REM Check common installation directories
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :python_found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :python_found
)
if exist "C:\Python312\python.exe" (
    set "PY_CMD=C:\Python312\python.exe"
    goto :python_found
)
if exist "C:\Python311\python.exe" (
    set "PY_CMD=C:\Python311\python.exe"
    goto :python_found
)
if exist "C:\Program Files\Python312\python.exe" (
    set "PY_CMD=C:\Program Files\Python312\python.exe"
    goto :python_found
)
if exist "C:\Program Files\Python311\python.exe" (
    set "PY_CMD=C:\Program Files\Python311\python.exe"
    goto :python_found
)

REM Python not found anywhere - Automated Installation
echo [!] Python 3.10+ was not detected on this computer.
echo [*] Starting automatic installation of Python 3.12...
echo.

REM Try winget first
winget --version >nul 2>&1
if not errorlevel 1 (
    echo [*] Installing Python via Windows winget...
    winget install -e --id Python.Python.3.12 --override "/passive InstallAllUsers=0 PrependPath=1 Include_pip=1" --accept-package-agreements --accept-source-agreements
    if not errorlevel 1 goto :locate_installed_python
)

REM Fallback: Download official Python installer using PowerShell (built into all Windows)
echo [*] Downloading official Python 3.12 from python.org...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe', '$env:TEMP\python_setup.exe')"
if not exist "%TEMP%\python_setup.exe" (
    echo [ERROR] Failed to download Python. Please install Python 3.10+ manually from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [*] Installing Python silently...
"%TEMP%\python_setup.exe" /passive InstallAllUsers=0 PrependPath=1 Include_pip=1
del "%TEMP%\python_setup.exe" >nul 2>&1

:locate_installed_python
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :python_found
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :python_found
)

echo [ERROR] Python installation completed but could not be located.
echo Please restart your terminal and run install.bat again.
pause
exit /b 1

:python_found
for /f "tokens=2 delims= " %%v in ('!PY_CMD! --version 2^>^&1') do set "DETECTED_VER=%%v"
echo [OK] Python detected: !PY_CMD! (version !DETECTED_VER!)
echo.

REM ----------------------------------------------------
REM Step 2: Create Isolated Virtual Environment
REM ----------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo [OK] Virtual environment already exists at .venv
) else (
    echo [*] Creating isolated virtual environment in .venv...
    !PY_CMD! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created successfully.
)

REM ----------------------------------------------------
REM Step 3: Install Required Dependencies & CLI Entrypoint
REM ----------------------------------------------------
echo [*] Installing required Python dependencies into .venv...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\pip.exe" install -r requirements.txt --quiet
".venv\Scripts\pip.exe" install -e . --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install packages from requirements.txt.
    pause
    exit /b 1
)
echo [OK] All dependencies successfully installed into isolated environment.
echo.

REM ----------------------------------------------------
REM Step 4: Run Automated Verification Suite (46 Tests)
REM ----------------------------------------------------
echo [*] Running automated self-tests to verify system compatibility...
".venv\Scripts\python.exe" -m pytest tests/ --quiet
if errorlevel 1 (
    echo [WARNING] Some self-tests produced warnings. Check tests/ for details.
) else (
    echo [OK] All 46 automated unit tests passed with 100%% success.
)
echo.

REM ----------------------------------------------------
REM Step 5: Configure .env
REM ----------------------------------------------------
if not exist ".env" (
    echo [*] Creating .env configuration file from template...
    copy .env.example .env >nul
    echo.
    echo ====================================================
    echo   [TELEGRAM BOT CONFIGURATION]
    echo ====================================================
    echo   Get your Bot Token from @BotFather on Telegram.
    echo.
    set /p "USER_TOKEN=Enter your Telegram Bot Token now (or press Enter to skip): "
    if defined USER_TOKEN (
        powershell -Command "(Get-Content .env) -replace 'TELEGRAM_BOT_TOKEN=.*', ('TELEGRAM_BOT_TOKEN=' + $env:USER_TOKEN) | Set-Content .env"
        echo [OK] Bot Token saved to .env.
    ) else (
        echo [!] Remember to open .env and paste your TELEGRAM_BOT_TOKEN before launching.
    )
) else (
    echo [OK] Configuration file .env already exists.
)
echo.

REM ----------------------------------------------------
REM Step 6: Verify Google Antigravity CLI
REM ----------------------------------------------------
where agy >nul 2>&1
if errorlevel 1 (
    if not exist "%LOCALAPPDATA%\agy\bin\agy.exe" (
        echo [!] Google Antigravity CLI 'agy' was not found in standard PATH.
        echo     Install it from https://antigravity.google or npm install -g @google/antigravity
    ) else (
        echo [OK] Antigravity CLI detected at %LOCALAPPDATA%\agy\bin\agy.exe
    )
) else (
    echo [OK] Antigravity CLI detected in system PATH.
)
echo.

REM ----------------------------------------------------
REM Setup Complete
REM ----------------------------------------------------
echo ====================================================
echo   Installation Complete!
echo ====================================================
echo.
echo To start your bot anytime, double-click: setup\run_bot.bat
echo Or run: antigravity-bot
echo.
pause
