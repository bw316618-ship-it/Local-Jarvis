#!/usr/bin/env bash
# Double-clickable (on macOS, via Finder) or terminal launcher for Jarvis on
# macOS/Linux -- the Unix counterpart to start_jarvis.bat.
#
# Note for macOS: zip extraction sometimes strips the executable bit, so a
# double-click might open this in a text editor instead of running it. If
# so, run `chmod +x start_jarvis.sh` once in Terminal, or just run
# `./start_jarvis.sh` directly.

set -e

# Always run from the folder this script lives in, no matter where it was
# launched from -- this is what makes "just run it" work after unzipping
# to any location.
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================"
echo "  Starting Local-Jarvis"
echo "============================================"
echo

# --- Check Python 3 is installed -----------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 was not found on your PATH."
    echo "Install Python 3.11 from https://www.python.org/downloads/"
    echo "or via your system's package manager (e.g. 'brew install python3')."
    echo
    read -p "Press Enter to exit..."
    exit 1
fi

# --- Create a virtual environment on first run ----------------------------
if [ ! -d "venv" ]; then
    echo "First-time setup: creating a virtual environment..."
    if ! python3 -m venv venv; then
        echo "[ERROR] Failed to create the virtual environment."
        read -p "Press Enter to exit..."
        exit 1
    fi
fi

source venv/bin/activate

# --- Install dependencies, only on first run ------------------------------
# A marker file inside venv/ (which is itself gitignored and wiped if you
# ever delete the venv) lets every launch after the first skip straight to
# running Jarvis instead of re-checking pip each time.
if [ ! -f "venv/.deps_installed" ]; then
    echo "First-time setup: installing dependencies, this can take a few minutes..."
    python3 -m pip install --upgrade pip >/dev/null
    if ! pip install -r requirements.txt; then
        echo "[ERROR] Failed to install dependencies. See the messages above."
        read -p "Press Enter to exit..."
        exit 1
    fi
    touch "venv/.deps_installed"
fi

# --- Sanity-check Ollama is available --------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
    echo "[WARNING] Ollama was not found on your PATH."
    echo "Jarvis needs Ollama installed and running locally."
    echo "Get it from https://ollama.com then run: ollama pull qwen3:8b"
    echo
fi

echo
echo "Launching Jarvis..."
echo
python3 main.py

echo
echo "Jarvis has exited."
read -p "Press Enter to close..."
