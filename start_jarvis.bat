@echo off
setlocal enabledelayedexpansion

:: Always run from the folder this script lives in, no matter where it
:: was double-clicked from -- this is what makes "just double-click it"
:: work after unzipping to any location.
cd /d "%~dp0"

echo ============================================
echo   Starting Local-Jarvis
echo ============================================
echo.

:: --- Check Python is installed -------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on your PATH.
    echo Install Python 3.11 from https://www.python.org/downloads/
    echo and make sure to check "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

:: --- Create a virtual environment on first run ---------------------------
if not exist "venv\" (
    echo First-time setup: creating a virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

:: --- Install dependencies, only on first run -----------------------------
:: A marker file inside venv/ (which is itself gitignored and wiped if you
:: ever delete the venv) lets every launch after the first skip straight to
:: running Jarvis instead of re-checking pip each time.
if not exist "venv\.deps_installed" (
    echo First-time setup: installing dependencies, this can take a few minutes...
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. See the messages above.
        pause
        exit /b 1
    )
    type nul > "venv\.deps_installed"
)

:: --- Sanity-check Ollama is available -------------------------------------
where ollama >nul 2>nul
if errorlevel 1 (
    echo [WARNING] Ollama was not found on your PATH.
    echo Jarvis needs Ollama installed and running locally.
    echo Get it from https://ollama.com then run: ollama pull llama3.1:8b
    echo.
)

echo.
echo Launching Jarvis...
echo.
python main.py

echo.
echo Jarvis has exited.
pause
