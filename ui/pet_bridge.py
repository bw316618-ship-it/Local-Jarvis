"""
Bridge between Jarvis and the Billo Rani desktop pet -- a separate
PyQt5 app (github.com/bw316618-ship-it/Desktop-Pet) that runs as its own
process with its own Qt event loop.

Jarvis's CLI loop and the pet's Qt loop can't be merged into one process,
so instead of real IPC, Jarvis just writes its current state to a small
shared JSON file, and the pet polls it on a timer and reacts. Same
low-dependency "shared file" pattern already used for config.py/
jarvis_config.json -- no message broker, no socket server, just a file
both sides agree on.

Writes are atomic (write to a temp file in the same directory, then
os.replace) so the pet never reads a half-written file mid-poll.

Failures here are swallowed, same as memory/audit_log.py and friends --
the pet is a nice-to-have visual companion, and a write hiccup here
should never interrupt an actual conversation turn.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "memory" / "pet_state.json"

# idle: nothing happening. listening: /voice or /wake capturing audio.
# thinking: waiting on the model (planning or a tool round). speaking:
# reply is being read aloud via /speak on. waiting_confirmation: a risky
# tool call needs a yes/no in the CLI -- gives the pet a way to visibly
# flag "check the terminal" rather than that prompt going unnoticed.
# error: something failed.
VALID_STATES = {
    "idle", "listening", "thinking", "speaking",
    "waiting_confirmation", "error",
}


def set_pet_state(state: str, message: str = "") -> None:
    """Tell the desktop pet what Jarvis is currently doing."""
    if state not in VALID_STATES:
        state = "idle"

    payload = {
        "state": state,
        "message": (message or "")[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, STATE_PATH)
    except Exception:
        pass
