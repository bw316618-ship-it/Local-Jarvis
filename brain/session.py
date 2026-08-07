"""
Shared plumbing for Jarvis's interaction surfaces. Previously main.py's
handle_message()/confirm_tool_call() and jarvis_daemon.py's
_daemon_confirm() each independently wired up HUD state broadcasting and
confirmation routing. JarvisSession + make_confirm_callback are now the
one place that logic lives.
"""

from memory.transcript import append_turn


def make_confirm_callback(console=None, hud=None):
    """Exactly one of console/hud should be given per surface: main.py's
    terminal loop always confirms via the terminal (console=...), even
    if the HUD happens to be open, since main.py never attaches its
    JarvisLLM to hud's chat routing. jarvis_daemon.py has no terminal at
    all, so it always confirms via the HUD (hud=...)."""

    def confirm(name: str, arguments: dict) -> bool:
        if hud is not None:
            return hud.request_confirmation(name, arguments)
        if console is not None:
            from rich.panel import Panel
            console.print(Panel(f"{name}({arguments})", title="[bold yellow]Confirm[/bold yellow]",
                                 border_style="yellow", expand=False))
            answer = console.input("[bold yellow]Allow this?[/bold yellow] [y/N] > ").strip().lower()
            return answer == "y"
        return False

    return confirm


class JarvisSession:
    """broadcast_text=False (main.py): pushes HUD *state* only -- the CLI
    is the chat surface, the HUD is just a visualizer alongside it.
    broadcast_text=True (jarvis_daemon.py via HUDBridge): pushes state
    *and* reply/step text -- the browser is the only chat surface."""

    def __init__(self, jarvis, hud=None, console=None, voice=None, broadcast_text=False):
        self.jarvis = jarvis
        self.hud = hud
        self.console = console
        self.voice = voice
        self.broadcast_text = broadcast_text

    def _tool_name(self, message: str) -> str:
        body = message[len("Step: "):] if message.startswith("Step: ") else message
        return body.split("(")[0].strip()

    def _render_step(self, message: str) -> None:
        from rich.panel import Panel
        if message.startswith("Plan:"):
            self.console.print(Panel(message[len("Plan:"):].strip(), title="[bold magenta]Plan[/bold magenta]",
                                      border_style="magenta", expand=False))
        else:
            body = message[len("Step: "):] if message.startswith("Step: ") else message
            self.console.print(f"[dim]  \u2192 {body}[/dim]")

    def handle_message(self, text: str, speak_replies: bool = False, session_log: list = None) -> str:
        if session_log is not None:
            append_turn(session_log, "user", text)

        pulse, stopped = None, [True]
        if self.console is not None:
            from ui.thinking import ThinkingPulse
            pulse = ThinkingPulse(self.console)
            pulse.start()
            stopped[0] = False
        if self.hud is not None:
            self.hud.set_state("thinking")

        def _stop_once():
            if pulse is not None and not stopped[0]:
                pulse.stop()
                stopped[0] = True
                self.console.print("[bold blue]Jarvis[/bold blue] [dim]\u203a[/dim] ", end="")

        def on_sentence(sentence: str) -> None:
            _stop_once()
            if self.hud is not None:
                (self.hud.broadcast_reply_chunk if self.broadcast_text else self.hud.set_state)(
                    sentence if self.broadcast_text else "speaking"
                )
            if self.console is not None:
                self.console.print(sentence, end=" ", soft_wrap=True, highlight=False)
            if speak_replies and self.voice is not None:
                self.voice.speak_async(sentence)

        def on_step(message: str) -> None:
            _stop_once()
            if self.hud is not None:
                if self.broadcast_text:
                    self.hud.broadcast_tool_step(message)
                else:
                    self.hud.set_state("tool", {"name": self._tool_name(message)})
            if self.console is not None:
                self._render_step(message)

        try:
            reply = self.jarvis.chat(text, on_step=on_step, on_sentence=on_sentence)
            _stop_once()
            if self.hud is not None:
                self.hud.set_state("idle")
            if self.console is not None:
                self.console.print()
                self.console.print()
            if session_log is not None:
                append_turn(session_log, "jarvis", reply)
            return reply
        except Exception as e:
            _stop_once()
            if self.hud is not None:
                self.hud.set_state("error")
            if self.console is not None:
                from rich.panel import Panel
                self.console.print()
                self.console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                self.console.print()
            if session_log is not None:
                append_turn(session_log, "jarvis", f"[error: {e}]")
            raise