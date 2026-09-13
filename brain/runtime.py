"""
Jarvis Core Runtime — Step 12.

This is the transport-independent application boundary.

The HUD, terminal, and future phone/network interfaces should talk to this
runtime instead of constructing JarvisLLM/JarvisSession themselves.

The runtime owns the assistant instance and adapts its output to whichever
surface requested the message. It does not know anything about WebSockets,
HTTP, browser authentication, or device transport.
"""

from brain.llm import JarvisLLM
from brain.session import JarvisSession, make_confirm_callback
from brain.session_state import SessionState


class JarvisRuntime:
    """Owns the actual Jarvis assistant independently of any UI.

    Each runtime owns exactly one SessionState, which is passed into the
    JarvisLLM instance so that mode, brain tier, mute, end-request, and
    creative scope are per-session rather than process-wide globals.

    Surfaces that intentionally share a runtime (e.g. the HUD and the
    first device in jarvis_backend_daemon.py) share the same SessionState
    automatically because they share the same JarvisLLM instance.
    """

    def __init__(self, jarvis=None):
        if jarvis is not None:
            # Caller-supplied instance (e.g. a test double).  Respect it
            # as-is; do not overwrite its session_state.
            self.jarvis = jarvis
            self.session_state = getattr(jarvis, "_session_state", None) or SessionState()
        else:
            self.session_state = SessionState()
            self.jarvis = JarvisLLM(session_state=self.session_state)
        self._surface_lock = None

    def handle_message(
        self,
        text: str,
        hud=None,
        console=None,
        voice=None,
        speak_replies: bool = False,
        session_log: list = None,
        map_context: str = None,
    ) -> str:
        """
        Process one user message through the core assistant.

        hud/console/voice are adapters for the current presentation surface.
        The runtime itself contains no transport code.
        """
        if hud is not None:
            callback = make_confirm_callback(hud=hud)
            self.jarvis.confirm_callback = callback
            broadcast_text = True
        elif console is not None:
            callback = make_confirm_callback(console=console)
            self.jarvis.confirm_callback = callback
            broadcast_text = False
        else:
            # No interactive confirmation surface means fail closed.
            self.jarvis.confirm_callback = make_confirm_callback()
            broadcast_text = False

        session = JarvisSession(
            self.jarvis,
            hud=hud,
            console=console,
            voice=voice,
            broadcast_text=broadcast_text,
        )

        return session.handle_message(
            text,
            speak_replies=speak_replies,
            session_log=session_log,
            map_context=map_context,
        )
