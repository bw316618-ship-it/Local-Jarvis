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


class JarvisRuntime:
    """Owns the actual Jarvis assistant independently of any UI."""

    def __init__(self, jarvis=None):
        self.jarvis = jarvis or JarvisLLM()
        self._surface_lock = None

    def handle_message(
        self,
        text: str,
        hud=None,
        console=None,
        voice=None,
        speak_replies: bool = False,
        session_log: list = None,
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
        )
