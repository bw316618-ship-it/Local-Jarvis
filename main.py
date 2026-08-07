import pyfiglet
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from brain.llm import JarvisLLM
from brain.session import JarvisSession, make_confirm_callback
from memory.audit_log import read_recent
from memory.conversation_memory import forget_all, list_facts
from memory.insights import get_suggestions
from memory.transcript import save_transcript
from tools.diagnostics import system_status, top_processes
from tools.file_index import count_pending_changes, index_files
from ui.hud_server import hud
from ui.splash import play_boot_animation
from voice.voice import JarvisVoice
from voice.wake_word import listen_for_wake_word

console = Console()

COMMANDS = [
    ("/help", "Show this command list"),
    ("/index", "(Re)index Documents/Desktop/Downloads for semantic file search"),
    ("/insights", "Check for proactive suggestions based on recent activity"),
    ("/status", "Show current CPU, memory, disk, and top processes at a glance"),
    ("/memory [category]", "List facts Jarvis has explicitly remembered about you"),
    ("/hud", "Toggle the graphical HUD (opens/closes a local browser tab)"),
    ("/voice [N]", "Speak your message -- stops automatically after a pause (or specify N seconds)"),
    ("/wake", "Always-listening mode -- say \"Hey Jarvis\" (Ctrl+C to stop)"),
    ("/speak on|off", "Toggle whether Jarvis speaks its replies aloud"),
    ("/save [path]", "Save this session's transcript to a Markdown file"),
    ("/log [n]", "Show the last n tool calls Jarvis has made (default 20)"),
    ("/forget", "Permanently clear Jarvis's long-term conversation memory and facts"),
    ("exit / quit", "End the session"),
]


def show_insights(suggestions: list, title: str = "Noticed a few things") -> None:
    if not suggestions:
        console.print("[dim]Nothing stands out right now.[/dim]\n")
        return
    body = "\n\n".join(f"- {s}" for s in suggestions)
    console.print(Panel(body, title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan", expand=False))
    console.print()


def print_banner() -> None:
    banner_text = pyfiglet.figlet_format("Jarvis", font="smslant")
    panel = Panel(
        f"[bold cyan]{banner_text}[/bold cyan]",
        subtitle=" local-first AI assistant ",
        subtitle_align="center",
        border_style="cyan",
        padding=(0, 2),
        width=44,
    )
    console.print(panel)
    console.print("[dim]Type[/dim] /help [dim]to see everything Jarvis can do.[/dim]\n")


def print_help() -> None:
    table = Table(border_style="dim", show_header=True, header_style="bold cyan", expand=False)
    table.add_column("Command")
    table.add_column("What it does")
    for cmd, desc in COMMANDS:
        table.add_row(cmd, desc)
    console.print(table)
    console.print(
        "[dim]Everything else is just a normal message -- Jarvis will run commands, "
        "manage files, control your mouse/keyboard, search the web, read the "
        "screen, and search indexed files as needed. It asks before anything "
        "risky.[/dim]\n"
    )


def main():
    play_boot_animation()
    print_banner()

    jarvis = JarvisLLM(confirm_callback=make_confirm_callback(console=console))
    voice = JarvisVoice()
    session = JarvisSession(jarvis, hud=hud, console=console, voice=voice, broadcast_text=False)

    import threading

    threading.Thread(target=voice.warm_up, daemon=True).start()

    speak_replies = False
    session_log = []

    try:
        startup_suggestions = get_suggestions()
        if startup_suggestions:
            show_insights(startup_suggestions, title="Noticed a few things")
    except Exception:
        pass

    try:
        pending = count_pending_changes()
        if pending:
            console.print(f"[dim]{pending} file(s) have changed since your last /index -- run /index to keep search results fresh.[/dim]\n")
    except Exception:
        pass

    while True:
        user_input = console.input("[bold green]You[/bold green] [dim]›[/dim] ")
        stripped = user_input.strip()
        lowered = stripped.lower()

        if lowered in ("exit", "quit"):
            hud.stop()
            console.print("[dim]Goodbye.[/dim]")
            break

        if lowered == "/help":
            print_help()
            continue

        if lowered == "/log" or lowered.startswith("/log "):
            parts = stripped.split()
            n = 20
            if len(parts) == 2 and parts[1].isdigit():
                n = int(parts[1])
            console.print(Panel(read_recent(n), title="[bold cyan]Recent tool calls[/bold cyan]", border_style="cyan", expand=False))
            console.print()
            continue

        if lowered == "/insights":
            show_insights(get_suggestions(), title="Insights")
            continue

        if lowered == "/status":
            try:
                body = system_status() + "\n\n" + top_processes()
                console.print(Panel(body, title="[bold cyan]System status[/bold cyan]", border_style="cyan", expand=False))
            except Exception as e:
                console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
            console.print()
            continue

        if lowered == "/memory" or lowered.startswith("/memory "):
            parts = stripped.split(maxsplit=1)
            category = parts[1] if len(parts) == 2 else None
            facts = list_facts(category)
            if facts:
                body = "\n".join(f"- {f}" for f in facts)
                title = f"Remembered facts{f' ({category})' if category else ''}"
                console.print(Panel(body, title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan", expand=False))
            else:
                console.print("[dim]Nothing remembered yet" + (f" under '{category}'." if category else ".") + "[/dim]")
            console.print()
            continue

        if lowered == "/hud":
            if hud.is_running():
                hud.stop()
                console.print("[dim]Graphical HUD closed.[/dim]\n")
            else:
                started = hud.start(open_browser=True)
                if started:
                    console.print(f"[dim]Graphical HUD opened at http://localhost:{hud.http_port} -- run /hud again to close it.[/dim]\n")
                else:
                    console.print(
                        Panel(
                            "Could not start the HUD (the 'websockets' package may not be installed -- run: pip install -r requirements.txt).",
                            title="[bold red]HUD unavailable[/bold red]",
                            border_style="red",
                            expand=False,
                        )
                    )
                    console.print()
            continue

        if lowered == "/forget":
            console.print(
                Panel(
                    "This permanently deletes everything Jarvis has learned from past conversations across all sessions. It cannot be undone.",
                    title="[bold yellow]Confirm[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
            )
            answer = console.input("[bold yellow]Clear long-term memory?[/bold yellow] [y/N] > ").strip().lower()
            if answer == "y":
                console.print(f"[bold cyan]{forget_all()}[/bold cyan]\n")
            else:
                console.print("[dim]Cancelled.[/dim]\n")
            continue

        if lowered == "/save" or lowered.startswith("/save "):
            parts = stripped.split(maxsplit=1)
            save_path = parts[1] if len(parts) == 2 else None
            result = save_transcript(session_log, path=save_path)
            console.print(f"[bold cyan]{result}[/bold cyan]\n")
            continue

        if lowered in ("/speak on", "/speak off"):
            speak_replies = lowered == "/speak on"
            console.print(f"[dim]Spoken replies turned {'on' if speak_replies else 'off'}.[/dim]\n")
            continue

        if lowered.startswith("/speak") and lowered not in ("/speak on", "/speak off"):
            console.print("[dim]Usage: /speak on  or  /speak off[/dim]\n")
            continue

        if lowered == "/index":
            console.print("[dim]Indexing Documents, Desktop, and Downloads -- this can take a while the first time...[/dim]")

            def show_progress(msg):
                console.print(f"[dim]  {msg}[/dim]")

            try:
                summary = index_files(progress=show_progress)
                console.print(f"[bold cyan]{summary}[/bold cyan]\n")
            except Exception as e:
                console.print(Panel(str(e), title="[bold red]Indexing failed[/bold red]", border_style="red", expand=False))
                console.print()
            continue

        if lowered == "/wake":
            console.print("[dim]Listening for \"Hey Jarvis\"... (Ctrl+C to stop)[/dim]")
            try:
                while True:
                    listen_for_wake_word()
                    console.print("[bold green]Jarvis (wake)[/bold green] › Yes?")

                    hud.set_state("listening")
                    try:
                        transcribed = voice.listen()
                    except RuntimeError as e:
                        hud.set_state("error")
                        console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                        continue

                    if not transcribed:
                        hud.set_state("idle")
                        console.print("[dim]Didn't catch anything -- listening for the wake word again...[/dim]\n")
                        continue

                    console.print(f"[bold green]You (voice)[/bold green] › {transcribed}")
                    session.handle_message(transcribed, speak_replies, session_log)
            except KeyboardInterrupt:
                hud.set_state("idle")
                console.print("\n[dim]Stopped listening for the wake word.[/dim]\n")
            except RuntimeError as e:
                hud.set_state("error")
                console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                console.print()
            continue

        if lowered == "/voice" or lowered.startswith("/voice "):
            parts = stripped.split()
            duration = None
            if len(parts) == 2 and parts[1].isdigit():
                duration = int(parts[1])

            hud.set_state("listening")
            try:
                console.print("[dim]Listening...[/dim]")
                transcribed = voice.listen(duration) if duration else voice.listen()
            except RuntimeError as e:
                hud.set_state("error")
                console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                console.print()
                continue

            if not transcribed:
                hud.set_state("idle")
                console.print("[dim]Didn't catch anything -- try again.[/dim]\n")
                continue

            console.print(f"[bold green]You (voice)[/bold green] › {transcribed}")
            user_input = transcribed

        session.handle_message(user_input, speak_replies, session_log)
        console.print(Rule(style="dim"))


if __name__ == "__main__":
    main()
