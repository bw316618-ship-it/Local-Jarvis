"""Per-session state for Jarvis.

Replaces the process-wide globals in voice/session_state.py and
voice/document_state.py with an instance that is owned by one
JarvisLLM / JarvisRuntime pair.

The global helpers in voice/session_state.py remain for callers that
have not yet been migrated (CLI, voice, HUD system-status) and for
backward compatibility with existing tests.  New code should obtain a
SessionState from the runtime and pass it through rather than reading
the globals directly.

Surfaces that intentionally share a runtime (e.g. the HUD and the first
device in jarvis_backend_daemon.py) share the same SessionState
automatically because they share the same JarvisLLM instance.
"""

import threading

from brain.mode_config import NORMAL, COMPANION, CREATIVE, CODING

VALID_MODES = {NORMAL, COMPANION, CREATIVE, CODING}

BRAIN_FAST = "fast"
BRAIN_HEAVY = "heavy"


class SessionState:
    """Mutable per-session state: mode, brain tier, mute, end-request,
    and active creative document/project.

    All attributes are thread-safe via a single reentrant lock so that
    the LLM thread and any surface thread can read/write concurrently
    without data races.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._mode = NORMAL
        self._brain_tier = BRAIN_FAST
        self._muted = False
        self._end_requested = False
        self._active_document = None
        self._active_project = None

    # ------------------------------------------------------------------
    # Mode
    # ------------------------------------------------------------------

    def current_mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> str:
        if mode not in VALID_MODES:
            raise ValueError(
                f"Unknown Jarvis mode '{mode}'. "
                f"Valid modes: {sorted(VALID_MODES)}"
            )
        with self._lock:
            self._mode = mode
            return self._mode

    def is_companion_mode(self) -> bool:
        return self.current_mode() == COMPANION

    def enter_companion_mode(self) -> None:
        self.set_mode(COMPANION)

    def exit_companion_mode(self) -> None:
        self.set_mode(NORMAL)

    def toggle_companion_mode(self) -> bool:
        if self.is_companion_mode():
            self.exit_companion_mode()
        else:
            self.enter_companion_mode()
        return self.is_companion_mode()

    def enter_creative_mode(self) -> None:
        self.set_mode(CREATIVE)

    def exit_creative_mode(self) -> None:
        self.set_mode(NORMAL)

    def enter_coding_mode(self) -> None:
        self.set_mode(CODING)

    def exit_coding_mode(self) -> None:
        self.set_mode(NORMAL)

    # ------------------------------------------------------------------
    # Brain tier
    # ------------------------------------------------------------------

    def current_brain_tier(self) -> str:
        with self._lock:
            return self._brain_tier

    def set_brain_tier(self, tier: str) -> str:
        if tier not in (BRAIN_FAST, BRAIN_HEAVY):
            raise ValueError(
                f"Unknown brain tier '{tier}'. "
                f"Valid tiers: {sorted((BRAIN_FAST, BRAIN_HEAVY))}"
            )
        with self._lock:
            self._brain_tier = tier
            return self._brain_tier

    def is_heavy_brain(self) -> bool:
        return self.current_brain_tier() == BRAIN_HEAVY

    def enter_heavy_brain(self) -> None:
        self.set_brain_tier(BRAIN_HEAVY)

    def exit_heavy_brain(self) -> None:
        self.set_brain_tier(BRAIN_FAST)

    # ------------------------------------------------------------------
    # Mute
    # ------------------------------------------------------------------

    def mute(self) -> None:
        with self._lock:
            self._muted = True

    def unmute(self) -> None:
        with self._lock:
            self._muted = False

    def is_muted(self) -> bool:
        with self._lock:
            return self._muted

    # ------------------------------------------------------------------
    # End-request (stop current turn)
    # ------------------------------------------------------------------

    def request_end(self) -> None:
        with self._lock:
            self._end_requested = True

    def is_end_requested(self) -> bool:
        with self._lock:
            return self._end_requested

    def clear_end_request(self) -> None:
        with self._lock:
            self._end_requested = False

    # ------------------------------------------------------------------
    # Creative document / project scope
    # ------------------------------------------------------------------

    def set_active_document(self, path: str) -> str:
        from pathlib import Path
        resolved = str(Path(path).expanduser().resolve())
        with self._lock:
            self._active_document = resolved
        return resolved

    def clear_active_document(self) -> None:
        with self._lock:
            self._active_document = None

    def get_active_document(self):
        with self._lock:
            return self._active_document

    def set_active_project(self, name: str) -> str:
        name = " ".join((name or "").strip().split())
        if not name:
            raise ValueError("Creative project name cannot be empty.")
        with self._lock:
            self._active_project = name
            self._active_document = None
        return name

    def clear_active_project(self) -> None:
        with self._lock:
            self._active_project = None

    def get_active_project(self):
        with self._lock:
            return self._active_project

    def clear_scope(self) -> None:
        with self._lock:
            self._active_document = None
            self._active_project = None
