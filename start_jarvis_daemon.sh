#!/usr/bin/env bash
# Double-clickable (on macOS, via Finder) or terminal launcher for the
# Local-Jarvis daemon on macOS/Linux -- the Unix counterpart to
# start_jarvis_daemon.bat.
#
# Runs jarvis_daemon.py: no terminal chat loop, just JarvisLLM + the HUD
# bridge. A browser tab opens automatically once the daemon is ready.
# Voice (/voice, /wake) and terminal-only commands (/log, /save,
# /insights, etc.) are NOT available here -- those are main.py CLI
# features. Use start_jarvis.sh instead if you need them.
#
# This script runs the daemon in the foreground (Ctrl+C to stop), same
# as start_jarvis.sh does for main.py -- useful for watching startup
# logs. To let it outlive the terminal that launched it, background/
# detach it yourself at the OS level, e.g.:
#   nohup ./start_jarvis_daemon.sh > jarvis_daemon.log 2>&1 &
# (see jarvis_daemon.py's own docstring for more on backgrounding it)
#
# Note for macOS: zip extraction sometimes strips the executable bit, so a
# double-click might open this in a text editor instead of running it. If
# so, run `chmod +x start_jarvis_daemon.sh` once in Terminal, or just run
# `./start_jarvis_daemon.sh` directly.

set -e

# Always run from the folder this script lives in, no matter where it was
# launched from -- same convention as start_jarvis.sh.
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================"
echo "  Starting Local-Jarvis Daemon"
echo "============================================"
echo
echo "This runs Jarvis headless (no terminal chat loop) with the"
echo "graphical HUD as the only interface. A browser tab will open"
echo "automatically once the daemon is ready."
echo
echo "Voice (/voice, /wake) and terminal-only commands (/log, /save,"
echo "/insights, etc.) are NOT available in daemon mode -- those are"
echo "main.py CLI features. Use start_jarvis.sh instead if you need them."
echo
echo "Press Ctrl+C to stop."
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
# Shares the same marker file as start_jarvis.sh, so if you've already run
# the regular launcher once, the daemon launcher skips straight to running
# instead of re-installing everything again.
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
    echo "Get it from https://ollama.com then run: ollama pull qwen3:4b"
    echo
fi

echo
echo "Launching Jarvis daemon..."
echo
python3 jarvis_daemon.py

echo
echo "Jarvis daemon has exited."
read -p "Press Enter to close..."
