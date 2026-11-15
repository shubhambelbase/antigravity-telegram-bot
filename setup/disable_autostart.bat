@echo off
setlocal
cd /d "%~dp0.."
title Disable Antigravity Bot Auto-Start

echo ====================================================
echo   Antigravity Bot - Disable Windows Auto-Start
echo ====================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from execution.autostart import disable_autostart; print('SUCCESS' if disable_autostart() else 'FAILED')" > "%TEMP%\autostart_res.txt" 2>&1
findstr /C:"SUCCESS" "%TEMP%\autostart_res.txt" >nul
if %errorlevel% equ 0 (
    echo [OK] Auto-Start has been DISABLED.
    echo.
    echo The bot will no longer start automatically when Windows boots.
    echo You can re-enable it anytime by running setup\enable_autostart.bat
    echo or by sending /autostart in Telegram.
) else (
    echo [ERROR] Failed to disable auto-start. Details:
    type "%TEMP%\autostart_res.txt"
)
if exist "%TEMP%\autostart_res.txt" del "%TEMP%\autostart_res.txt"

echo.
pause
