@echo off
title Antigravity Telegram Bot
echo ====================================================
echo Starting Antigravity Telegram Bot...
echo ====================================================
cd /d "%~dp0"
call .venv\Scripts\activate
python -m execution.telegram_bot
pause
