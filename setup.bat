@echo off
REM gib-bot Windows setup script.
REM Run by double-clicking in Explorer, OR with `./setup.bat` in Git Bash.
REM Requires Python 3.10+ and Git already installed.

echo === gib-bot setup ===
echo.

REM Check Python is on PATH
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python is not on your PATH.
    echo.
    echo Install Python 3.12 ^(64-bit^) from https://www.python.org/downloads/
    echo and CHECK "Add python.exe to PATH" on the first install screen.
    echo Then re-run this script.
    echo.
    pause
    exit /b 1
)

REM Create the virtual environment if it doesn't exist
if not exist .venv (
    echo Creating virtual environment ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Install dependencies into the venv
echo Installing dependencies into .venv...
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

REM Copy .env template if .env doesn't exist (preserves any prior edits)
if not exist .env (
    echo Creating .env from template...
    copy .env.example .env >nul
)

echo.
echo === Setup complete ===
echo.
echo Opening .env in Notepad. Paste in your Helius API key and your wallet
echo pubkey, then save and close Notepad.
echo.
notepad .env

echo.
echo To run the bot:
echo   1. Open Git Bash and cd to this folder
echo   2. Run: source .venv/Scripts/activate
echo   3. Run any command from the README ^(e.g. python cli.py inventory^)
echo.
pause
