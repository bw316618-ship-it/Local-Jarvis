"""
Boot splash animation for Jarvis -- an animated circular "arc reactor" HUD
rendered directly in the terminal via Rich, in the visual language of the
J.A.R.V.I.S. reference art (concentric rotating rings, tick marks, a radar
sweep, and a centered wordmark).

This is intentionally CLI-native (no new dependencies beyond `rich`, which
main.py already requires) as a first step toward a full graphical HUD later.
play_boot_animation() is meant to run once at startup, right before the
existing pyfiglet banner in main.py, and is safe to skip entirely (no-ops)
if the terminal can't support Live rendering (piped output, CI, etc.) --
a rendering hiccup here should never block Jarvis from actually starting.
"""

import math
import time

from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

WIDTH = 62            # character columns for the HUD canvas
HEIGHT = 31            # character rows (odd, so there's a true center row)
CENTER_X = WIDTH / 2
CENTER_Y = HEIGHT / 2
ASPECT = 2.15          # terminal cells are taller than wide; squashes circles back round

# (radius, tick_count, char, style, spin_speed in radians/frame)
RINGS = [
    (13.5, 60, "\u00b7", "cyan", 0.09),
    (11.0, 40, "\u2500", "bright_cyan", -0.14),
    (8.5, 28, "\u2022", "cyan", 0.20),
]

WORDMARK = "J.A.R.V.I.S."
SUBTITLE = "SYSTEMS ONLINE"

FRAME_COUNT = 42
FRAME_DELAY = 0.045


def _build_frame(t: int) -> Text:
    grid = [[" " for _ in range(WIDTH)] for _ in range(HEIGHT)]
    styles = [[None for _ in range(WIDTH)] for _ in range(HEIGHT)]

    for radius, tick_count, char, style, speed in RINGS:
        offset = t * speed
        for i in range(tick_count):
            angle = offset + (2 * math.pi * i / tick_count)
            x = CENTER_X + radius * math.cos(angle) * ASPECT / 2
            y = CENTER_Y + radius * math.sin(angle) / 2
            xi, yi = int(round(x)), int(round(y))
            if 0 <= yi < HEIGHT and 0 <= xi < WIDTH:
                grid[yi][xi] = char
                styles[yi][xi] = style

    # A single bright "sweep" marker orbiting the outer ring, like radar.
    sweep_angle = t * 0.12
    sx = CENTER_X + 15 * math.cos(sweep_angle) * ASPECT / 2
    sy = CENTER_Y + 15 * math.sin(sweep_angle) / 2
    sxi, syi = int(round(sx)), int(round(sy))
    if 0 <= syi < HEIGHT and 0 <= sxi < WIDTH:
        grid[syi][sxi] = "\u25cf"
        styles[syi][sxi] = "bold yellow"

    # Centered wordmark + subtitle, punched through the middle of the rings.
    label_row = HEIGHT // 2
    start_col = int(CENTER_X - len(WORDMARK) / 2)
    for i, ch in enumerate(WORDMARK):
        col = start_col + i
        if 0 <= col < WIDTH:
            grid[label_row][col] = ch
            styles[label_row][col] = "bold white"

    sub_row = label_row + 2
    start_col = int(CENTER_X - len(SUBTITLE) / 2)
    for i, ch in enumerate(SUBTITLE):
        col = start_col + i
        if 0 <= col < WIDTH:
            grid[sub_row][col] = ch
            styles[sub_row][col] = "dim cyan"

    text = Text()
    for row in range(HEIGHT):
        for col in range(WIDTH):
            ch = grid[row][col]
            style = styles[row][col] or "grey23"
            text.append(ch, style=style)
        text.append("\n")
    return text


def play_boot_animation(console: Console = None) -> None:
    """Play a short animated boot HUD, then clear it (transient=True).

    No-ops safely if the terminal can't support Live rendering (e.g. piped
    output, CI) so it never blocks startup on an unusual terminal.
    """
    console = console or Console()

    if not console.is_terminal:
        return

    try:
        with Live(console=console, refresh_per_second=30, transient=True) as live:
            for t in range(FRAME_COUNT):
                frame = _build_frame(t)
                panel = Panel(
                    Align.center(frame),
                    border_style="cyan",
                    padding=(0, 2),
                )
                live.update(panel)
                time.sleep(FRAME_DELAY)
    except Exception:
        pass
