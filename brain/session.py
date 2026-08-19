"""
Shared plumbing for Jarvis's interaction surfaces. Previously main.py's
handle_message()/confirm_tool_call() and jarvis_daemon.py's
_daemon_confirm() each independently wired up HUD state broadcasting and
confirmation routing. JarvisSession + make_confirm_callback are now the
one place that logic lives.

Output fan-out (console / HUD / voice) is expressed as a list of
OutputSink objects rather than hardcoded `if self.hud / if self.console`
branches. Adding a fourth surface (desktop overlay, phone client, ...)
means writing one small OutputSink subclass and passing it in via
`extra_sinks=` -- it does not require touching on_step/on_sentence here.
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


class OutputSink:
    """One presentation surface's reaction to session lifecycle events.
    Override only the hooks that apply -- everything else is a no-op.

    Hooks fire in this order per handle_message() call:
        start() -> [first_output() once, before the first step/sentence]
        -> step()/sentence() any number of times, interleaved
        -> idle()  (success)  or  error()  (exception)
    """

    def start(self) -> None:
        pass

    def first_output(self) -> None:
        pass

    def sentence(self, text: str, speak_replies: bool) -> None:
        pass

    def step(self, message: str, tool_name: str) -> None:
        pass

    def idle(self) -> None:
        pass

    def error(self, err: Exception) -> None:
        pass


class ConsoleSink(OutputSink):
    """Rich-console terminal output: a thinking pulse that yields to the
    first streamed token, then plain printed sentences/step panels."""

    def __init__(self, console):
        self.console = console
        self._pulse = None
        self._stopped = True

    def start(self) -> None:
        from ui.thinking import ThinkingPulse
        self._pulse = ThinkingPulse(self.console)
        self._pulse.start()
        self._stopped = False

    def first_output(self) -> None:
        if self._pulse is not None and not self._stopped:
            self._pulse.stop()
            self._stopped = True
            self.console.print("[bold blue]Jarvis[/bold blue] [dim]\u203a[/dim] ", end="")

    def sentence(self, text: str, speak_replies: bool) -> None:
        def sentence(self, text: str, speak_replies: bool) -> None:
            self.console.print(text, soft_wrap=True, highlight=False)

    def step(self, message: str, tool_name: str) -> None:
        from rich.panel import Panel
        if message.startswith("Plan:"):
            self.console.print(Panel(message[len("Plan:"):].strip(), title="[bold magenta]Plan[/bold magenta]",
                                      border_style="magenta", expand=False))
        else:
            body = message[len("Step: "):] if message.startswith("Step: ") else message
            self.console.print(f"[dim]  \u2192 {body}[/dim]")

    def idle(self) -> None:
        self.console.print()
        self.console.print()

    def error(self, err: Exception) -> None:
        from rich.panel import Panel
        self.console.print()
        self.console.print(Panel(str(err), title="[bold red]Error[/bold red]", border_style="red", expand=False))
        self.console.print()


class HudSink(OutputSink):
    """Browser HUD output. broadcast_text=False (main.py): the CLI is the
    chat surface, the HUD is just a state visualizer alongside it, so
    only set_state() is pushed. broadcast_text=True (jarvis_daemon.py via
    HUDBridge): the browser is the only chat surface, so reply/step text
    is broadcast too."""

    def __init__(self, hud, broadcast_text: bool):
        self.hud = hud
        self.broadcast_text = broadcast_text

    def start(self) -> None:
        self.hud.set_state("thinking")

    def sentence(self, text: str, speak_replies: bool) -> None:
        if self.broadcast_text:
            self.hud.broadcast_reply_chunk(text)
        else:
            self.hud.set_state("speaking")

    def step(self, message: str, tool_name: str) -> None:
        if self.broadcast_text:
            self.hud.broadcast_tool_step(message)
        else:
            self.hud.set_state("tool", {"name": tool_name})

    def idle(self) -> None:
        self.hud.set_state("idle")

    def error(self, err: Exception) -> None:
        self.hud.set_state("error")


class VoiceSink(OutputSink):
    """Text-to-speech output. Only reacts to completed sentences, and
    only when the caller asked for spoken replies on this turn."""

    def __init__(self, voice):
        self.voice = voice

    def sentence(self, text: str, speak_replies: bool) -> None:
        if speak_replies:
            self.voice.speak_async(text)


class JarvisSession:
    """broadcast_text=False (main.py): pushes HUD *state* only -- the CLI
    is the chat surface, the HUD is just a visualizer alongside it.
    broadcast_text=True (jarvis_daemon.py via HUDBridge): pushes state
    *and* reply/step text -- the browser is the only chat surface."""

    def __init__(self, jarvis, hud=None, console=None, voice=None, broadcast_text=False, extra_sinks=None):
        self.jarvis = jarvis
        self.hud = hud
        self.console = console
        self.voice = voice
        self.broadcast_text = broadcast_text

        self._sinks = []
        if console is not None:
            self._sinks.append(ConsoleSink(console))
        if hud is not None:
            self._sinks.append(HudSink(hud, broadcast_text))
        if voice is not None:
            self._sinks.append(VoiceSink(voice))
        if extra_sinks:
            self._sinks.extend(extra_sinks)

    @staticmethod
    def _tool_name(message: str) -> str:
        body = message[len("Step: "):] if message.startswith("Step: ") else message
        return body.split("(")[0].strip()

    def handle_message(self, text: str, speak_replies: bool = False, session_log: list = None) -> str:
        if session_log is not None:
            append_turn(session_log, "user", text)

        for sink in self._sinks:
            sink.start()

        first_output_done = [False]

        def _first_output_once():
            if not first_output_done[0]:
                first_output_done[0] = True
                for sink in self._sinks:
                    sink.first_output()

        def on_sentence(sentence: str) -> None:
            _first_output_once()
            for sink in self._sinks:
                sink.sentence(sentence, speak_replies)

        def on_step(message: str) -> None:
            _first_output_once()
            tool_name = self._tool_name(message)
            for sink in self._sinks:
                sink.step(message, tool_name)

        try:
            reply = self.jarvis.chat(text, on_step=on_step, on_sentence=on_sentence)
            _first_output_once()
            for sink in self._sinks:
                sink.idle()
            if session_log is not None:
                append_turn(session_log, "jarvis", reply)
            return reply
        except Exception as e:
            _first_output_once()
            for sink in self._sinks:
                sink.error(e)
            if session_log is not None:
                append_turn(session_log, "jarvis", f"[error: {e}]")
            raise
