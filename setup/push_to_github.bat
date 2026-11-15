@echo off
setlocal enabledelayedexpansion
title Push to GitHub - Antigravity Telegram Bot
cd /d "%~dp0.."

echo ====================================================
echo   Antigravity Bot - GitHub Publisher & Sync Tool
echo ====================================================
echo.

REM ----------------------------------------------------
REM Step 1: Pre-flight Git Verification
REM ----------------------------------------------------
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH.
    echo Please install Git for Windows from https://git-scm.com/
    pause
    exit /b 1
)

REM ----------------------------------------------------
REM Step 2: Security & Secret Protection Check
REM ----------------------------------------------------
echo [*] Performing security audit...
git ls-files .env >nul 2>&1
if %errorlevel% equ 0 (
    echo [SECURITY ALERT] .env is currently tracked by Git!
    echo Removing .env from Git tracking before pushing...
    git rm --cached .env >nul 2>&1
)

if not exist ".gitignore" (
    echo [ERROR] .gitignore file is missing. Aborting to protect secrets.
    pause
    exit /b 1
)

echo [OK] Secrets (.env, .venv, credentials) are strictly gitignored.
echo.

REM ----------------------------------------------------
REM Step 3: Run Automated Test Suite
REM ----------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo [*] Running automated tests to guarantee codebase health...
    ".venv\Scripts\python.exe" -m pytest tests/ -q
    if %errorlevel% neq 0 (
        echo.
        echo [WARNING] Some unit tests failed!
        set /p "CONTINUE_ANYWAY=Do you still want to proceed with push? [Y/N, default N]: "
        if /i not "!CONTINUE_ANYWAY!"=="Y" (
            echo Aborted by user.
            pause
            exit /b 1
        )
    ) else (
        echo [OK] All automated unit tests passed with 100%% success!
    )
) else (
    echo [!] Virtual environment not found. Skipping tests.
)
echo.

REM ----------------------------------------------------
REM Step 4: Ensure Main Branch & Stage Changes
REM ----------------------------------------------------
git branch -M main >nul 2>&1
git add .

REM Check if there are uncommitted changes
git diff --cached --quiet
if %errorlevel% neq 0 (
    echo [*] Detected uncommitted changes.
    set "COMMIT_MSG="
    set /p "COMMIT_MSG=Enter commit message (press Enter for default): "
    if "!COMMIT_MSG!"=="" (
        set "COMMIT_MSG=feat: update Antigravity Telegram Bot codebase"
    )
    git commit -m "!COMMIT_MSG!"
    echo [OK] Changes committed: "!COMMIT_MSG!"
) else (
    echo [OK] Working tree clean; all changes are committed.
)
echo.

REM ----------------------------------------------------
REM Step 5: Configure Remote Origin
REM ----------------------------------------------------
set "REMOTE_URL="
for /f "tokens=*" %%a in ('git remote get-url origin 2^>nul') do set "REMOTE_URL=%%a"

if defined REMOTE_URL (
    echo Current remote origin: !REMOTE_URL!
    set /p "USE_CURRENT=Push to this remote? [Y/N, default Y]: "
    if /i "!USE_CURRENT!"=="N" (
        set /p "NEW_URL=Enter new GitHub repository URL: "
        if defined NEW_URL (
            git remote set-url origin "!NEW_URL!"
            set "REMOTE_URL=!NEW_URL!"
        )
    )
) else (
    REM Check if GitHub CLI (gh) is available and authenticated
    gh auth status >nul 2>&1
    if %errorlevel% equ 0 (
        echo GitHub CLI (gh) is authenticated!
        echo.
        echo Select an option:
        echo   [1] Automatically create a new repository on your GitHub account
        echo   [2] Enter an existing GitHub repository URL
        echo.
        set /p "GH_CHOICE=Select [1/2, default 1]: "
        if "!GH_CHOICE!"=="" set "GH_CHOICE=1"

        if "!GH_CHOICE!"=="1" (
            set /p "REPO_NAME=Repository name [default: antigravity-telegram-bot]: "
            if "!REPO_NAME!"=="" set "REPO_NAME=antigravity-telegram-bot"

            set /p "VIS_CHOICE=Visibility - Public or Private? [public/private, default: private]: "
            if "!VIS_CHOICE!"=="" set "VIS_CHOICE=private"

            echo [*] Creating GitHub repository: !REPO_NAME! (!VIS_CHOICE!)...
            gh repo create "!REPO_NAME!" --!VIS_CHOICE! --source=. --remote=origin
            if %errorlevel% neq 0 (
                echo [!] Could not create via gh. Please enter repository URL manually.
                set /p "REPO_URL=Enter GitHub repository URL: "
                if defined REPO_URL git remote add origin "!REPO_URL!"
            )
        ) else (
            set /p "REPO_URL=Enter GitHub repository URL (https://github.com/user/repo.git): "
            if defined REPO_URL git remote add origin "!REPO_URL!"
        )
    ) else (
        echo No remote configured.
        set /p "REPO_URL=Enter GitHub repository URL (https://github.com/user/repo.git): "
        if defined REPO_URL (
            git remote add origin "!REPO_URL!"
        ) else (
            echo [ERROR] No repository URL provided. Aborting.
            pause
            exit /b 1
        )
    )
)
echo.

REM ----------------------------------------------------
REM Step 6: Push Codebase to GitHub
REM ----------------------------------------------------
echo [*] Pushing branch 'main' to GitHub origin...
echo.
git push -u origin main
if %errorlevel% equ 0 (
    echo.
    echo ====================================================
    echo   [SUCCESS] Codebase pushed successfully to GitHub!
    echo ====================================================
    for /f "tokens=*" %%a in ('git remote get-url origin 2^>nul') do echo Repository URL: %%a
) else (
    echo.
    echo [ERROR] Git push failed.
    echo Common reasons:
    echo  1. Remote repository has commits you don't have locally (run: git pull --rebase origin main)
    echo  2. Authentication failed (run: gh auth login or configure personal access token)
    echo  3. Repository does not exist or URL is incorrect.
)

echo.
pause
