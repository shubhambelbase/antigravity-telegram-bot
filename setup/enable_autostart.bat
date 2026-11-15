@echo off
setlocal
cd /d "%~dp0.."
title Enable Antigravity Bot Auto-Start

echo ====================================================
echo   Antigravity Bot - Enable Windows Auto-Start
echo ====================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from execution.autostart import enable_autostart; print('SUCCESS' if enable_autostart() else 'FAILED')" > "%TEMP%\autostart_res.txt" 2>&1
findstr /C:"SUCCESS" "%TEMP%\autostart_res.txt" >nul
if %errorlevel% equ 0 (
    echo [OK] Auto-Start is now ENABLED!
    echo.
    echo The Antigravity Telegram Bot will start silently in the background
    echo every time you turn on or log in to your laptop.
    echo.
    echo You can manage it anytime:
    echo  - In Telegram: Send /autostart or toggle in /status
    echo  - In Windows: Double-click setup\disable_autostart.bat
) else (
    echo [ERROR] Failed to enable auto-start. Details:
    type "%TEMP%\autostart_res.txt"
)
if exist "%TEMP%\autostart_res.txt" del "%TEMP%\autostart_res.txt"

echo.
pause
