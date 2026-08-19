"""
Shared plumbing for Jarvis's interaction surfaces.

JarvisSession is the central routing layer for console, HUD, voice, and
additional output surfaces.

Output fan-out is expressed as a list of OutputSink objects. Adding another
surface means implementing one OutputSink subclass and passing it through
extra_sinks=.
"""

from memory.transcript import append_turn


def make_confirm_callback(console=None, hud=None):
    """Create the confirmation callback used by a Jarvis surface.

    HUD takes priority when supplied. Otherwise confirmation is performed
    through the terminal console.
    """

    def confirm(name: str, arguments: dict) -> bool:
        if hud is not None:
            return hud.request_confirmation(name, arguments)

        if console is not None:
            from rich.panel import Panel

            console.print(
                Panel(
                    f"{name}({arguments})",
                    title="[bold yellow]Confirm[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
            )

            answer = console.input(
                "[bold yellow]Allow this?[/bold yellow] [y/N] > "
            ).strip().lower()

            return answer == "y"

        return False

    return confirm


class OutputSink:
    """One presentation surface's reaction to session lifecycle events.

    Hooks fire in this order per handle_message() call:

        start()
        -> first_output() once
        -> step()/sentence() any number of times
        -> idle() on success
           OR
        -> error() on exception
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
    """Rich-console terminal output.

    A thinking pulse is displayed until the first actual output arrives.
    Completed sentences are printed independently rather than being appended
    to one giant line.
    """

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

            self.console.print(
                "[bold blue]Jarvis[/bold blue] [dim]›[/dim] ",
                end="",
            )

    def sentence(self, text: str, speak_replies: bool) -> None:
        """Print one completed streamed sentence.

        Do NOT use end=" " here. That was causing every sentence to collapse
        into one continuous terminal line.
        """
        if not text:
            return

        self.console.print(
            text,
            soft_wrap=True,
            highlight=False,
        )

    def step(self, message: str, tool_name: str) -> None:
        from rich.panel import Panel

        if message.startswith("Plan:"):
            self.console.print(
                Panel(
                    message[len("Plan:"):].strip(),
                    title="[bold magenta]Plan[/bold magenta]",
                    border_style="magenta",
                    expand=False,
                )
            )
        else:
            body = (
                message[len("Step: "):]
                if message.startswith("Step: ")
                else message
            )

            self.console.print(
                f"[dim]  → {body}[/dim]"
            )

    def idle(self) -> None:
        self.console.print()
        self.console.print()

    def error(self, err: Exception) -> None:
        from rich.panel import Panel

        self.console.print()
        self.console.print(
            Panel(
                str(err),
                title="[bold red]Error[/bold red]",
                border_style="red",
                expand=False,
            )
        )
        self.console.print()


class HudSink(OutputSink):
    """Browser HUD output.

    broadcast_text=False:
        The CLI is the chat surface and the HUD is only a state visualizer.

    broadcast_text=True:
        The browser is the chat surface, so reply and tool text are broadcast.
    """

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
            self.hud.set_state(
                "tool",
                {"name": tool_name},
            )

    def idle(self) -> None:
        self.hud.set_state("idle")

    def error(self, err: Exception) -> None:
        self.hud.set_state("error")


class VoiceSink(OutputSink):
    """Text-to-speech output.

    Only completed sentences are spoken, and only when spoken replies are
    enabled for the current turn.
    """

    def __init__(self, voice):
        self.voice = voice

    def sentence(self, text: str, speak_replies: bool) -> None:
        if speak_replies and text:
            self.voice.speak_async(text)


class JarvisSession:
    """Central interaction/output router for Jarvis.

    The console, HUD, voice system, and optional additional sinks all receive
    the same lifecycle events.
    """

    def __init__(
        self,
        jarvis,
        hud=None,
        console=None,
        voice=None,
        broadcast_text=False,
        extra_sinks=None,
    ):
        self.jarvis = jarvis
        self.hud = hud
        self.console = console
        self.voice = voice
        self.broadcast_text = broadcast_text

        self._sinks = []

        if console is not None:
            self._sinks.append(
                ConsoleSink(console)
            )

        if hud is not None:
            self._sinks.append(
                HudSink(
                    hud,
                    broadcast_text,
                )
            )

        if voice is not None:
            self._sinks.append(
                VoiceSink(voice)
            )

        if extra_sinks:
            self._sinks.extend(extra_sinks)

    @staticmethod
    def _tool_name(message: str) -> str:
        body = (
            message[len("Step: "):]
            if message.startswith("Step: ")
            else message
        )

        return body.split("(")[0].strip()

    def handle_message(
        self,
        text: str,
        speak_replies: bool = False,
        session_log: list = None,
    ) -> str:

        if session_log is not None:
            append_turn(
                session_log,
                "user",
                text,
            )

        for sink in self._sinks:
            sink.start()

        first_output_done = [False]

        # Tracks whether the model actually produced output through the
        # streaming callback. This lets us safely fall back to the returned
        # reply when the LLM returns a complete response without callbacks.
        sentence_output_done = [False]

        def _first_output_once():
            if not first_output_done[0]:
                first_output_done[0] = True

                for sink in self._sinks:
                    sink.first_output()

        def on_sentence(sentence: str) -> None:
            if not sentence:
                return

            _first_output_once()

            sentence_output_done[0] = True

            for sink in self._sinks:
                sink.sentence(
                    sentence,
                    speak_replies,
                )

        def on_step(message: str) -> None:
            _first_output_once()

            tool_name = self._tool_name(message)

            for sink in self._sinks:
                sink.step(
                    message,
                    tool_name,
                )

        try:
            reply = self.jarvis.chat(
                text,
                on_step=on_step,
                on_sentence=on_sentence,
            )

            _first_output_once()

            # Safety net:
            #
            # Normally JarvisLLM streams completed sentences through
            # on_sentence(). However, a backend/model can return a completed
            # response without producing those callbacks.
            #
            # Without this fallback, the terminal would show:
            #
            #   Jarvis ›
            #
            # and then nothing.
            #
            # Only use the fallback if no sentence was rendered, preventing
            # the response from being printed twice.
            if (
                not sentence_output_done[0]
                and reply
                and reply.strip()
            ):
                for sink in self._sinks:
                    sink.sentence(
                        reply,
                        speak_replies,
                    )

            for sink in self._sinks:
                sink.idle()

            if session_log is not None:
                append_turn(
                    session_log,
                    "jarvis",
                    reply,
                )

            return reply

        except Exception as e:
            _first_output_once()

            for sink in self._sinks:
                sink.error(e)

            if session_log is not None:
                append_turn(
                    session_log,
                    "jarvis",
                    f"[error: {e}]",
                )

            raise
