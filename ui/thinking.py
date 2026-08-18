"""
Inline "thinking" pulse for Jarvis -- a small, fast, single-line cousin of
the boot HUD (ui/splash.py) that plays in place while Jarvis is processing
a request, before the first real output (a tool step or the first
streamed sentence) is ready to show.

Runs on a background thread via Rich's Live so it never blocks the actual
chat() call, which is what's producing that real output. The caller
starts the pulse right before invoking jarvis.chat() and stops it the
instant the first on_step/on_sentence callback fires, so the pulse never
overlaps with real content -- it just gets cleared (Live's transient=True)
and normal output takes its place on the same line.

Deliberately single-line and cheap to render (no per-frame grid math like
splash.py's full HUD) since this fires on every message, not once at
startup -- it needs to feel instant to start and stop, not like its own
mini animation to sit through.
"""

import threading
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

# Rotating quarter-circle glyphs -- reads as a small spinning ring, the
# same visual idea as splash.py's rotating tick marks, just condensed to
# one animated character instead of a whole grid.
RING_FRAMES = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]  # ◐ ◓ ◑ ◒

FRAME_DELAY = 0.08


def _build_frame(t: int) -> Text:
    ring_char = RING_FRAMES[t % len(RING_FRAMES)]
    dots = "." * (t % 4)

    text = Text()
    text.append("Jarvis ", style="bold blue")
    text.append("\u203a ", style="dim")
    text.append(ring_char, style="bold cyan")
    text.append(f" thinking{dots}", style="dim cyan")
    return text


class ThinkingPulse:
    """Background single-line Live animation.

    Call .start() right before a blocking/streaming operation, .stop() the
    moment real output begins. Safe to call .stop() multiple times, or
    without a matching .start() (e.g. non-terminal output) -- both are
    no-ops in that case.
    """

    def __init__(self, console: Console = None):
        self.console = console or Console()
        self._thread = None
        self._stop_event = threading.Event()
        self._started = False

    def _run(self):
        try:
            with Live(console=self.console, refresh_per_second=20, transient=True) as live:
                t = 0
                while not self._stop_event.is_set():
                    live.update(_build_frame(t))
                    t += 1
                    time.sleep(FRAME_DELAY)
        except Exception:
            # A rendering hiccup here should never block or crash the
            # actual reply this pulse is standing in for.
            pass

    def start(self):
        if not self.console.is_terminal or self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._started:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
