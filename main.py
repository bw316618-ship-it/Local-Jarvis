import pyfiglet
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from brain.llm import JarvisLLM
from voice.voice import JarvisVoice
from voice.wake_word import listen_for_wake_word
from tools.file_index import index_files
from memory.transcript import append_turn, save_transcript
from memory.audit_log import read_recent

console = Console()

COMMANDS = [
    ("/help", "Show this command list"),
    ("/index", "(Re)index Documents/Desktop/Downloads for semantic file search"),
    ("/voice [N]", "Speak your message instead of typing it (optional N-second duration)"),
    ("/wake", "Always-listening mode -- say \"Hey Jarvis\" (Ctrl+C to stop)"),
    ("/speak on|off", "Toggle whether Jarvis speaks its replies aloud"),
    ("/save [path]", "Save this session's transcript to a Markdown file"),
    ("/log [n]", "Show the last n tool calls Jarvis has made (default 20)"),
    ("exit / quit", "End the session"),
]


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


def confirm_tool_call(name: str, arguments: dict) -> bool:
    console.print(
        Panel(
            f"{name}({arguments})",
            title="[bold yellow]Confirm[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
    )
    answer = console.input("[bold yellow]Allow this?[/bold yellow] [y/N] > ").strip().lower()
    return answer == "y"


def show_step(message: str) -> None:
    if message.startswith("Plan:"):
        plan_body = message[len("Plan:"):].strip()
        console.print(Panel(plan_body, title="[bold magenta]Plan[/bold magenta]", border_style="magenta", expand=False))
    else:
        console.print(f"[dim]  \u2192 {message[len('Step: '):] if message.startswith('Step: ') else message}[/dim]")


def handle_message(jarvis: JarvisLLM, voice: JarvisVoice, text: str, speak_replies: bool, session_log: list) -> None:
    """Send `text` to Jarvis and print (and optionally speak) the reply.

    Shared by the normal typed-input loop and /wake mode, so a spoken
    command triggered by the wake word goes through the exact same path
    as a typed one. Also records both sides of the turn into `session_log`
    for /save -- this is just an in-memory transcript for export, not
    memory Jarvis itself uses; each chat() call still starts fresh.
    """
    append_turn(session_log, "user", text)
    try:
        with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots"):
            reply = jarvis.chat(text, on_step=show_step)
        console.print(Panel(Markdown(reply), title="[bold blue]Jarvis[/bold blue]", border_style="blue", expand=False))
        console.print()
        append_turn(session_log, "jarvis", reply)
        if speak_replies:
            voice.speak(reply)
    except Exception as e:
        console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
        console.print()
        append_turn(session_log, "jarvis", f"[error: {e}]")


def main():
    print_banner()

    jarvis = JarvisLLM(confirm_callback=confirm_tool_call)
    voice = JarvisVoice()
    speak_replies = False
    session_log = []

    while True:
        user_input = console.input("[bold green]You[/bold green] [dim]\u203a[/dim] ")
        stripped = user_input.strip()
        lowered = stripped.lower()

        if lowered in ("exit", "quit"):
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
                    console.print("[bold green]Jarvis (wake)[/bold green] \u203a Yes?")

                    try:
                        transcribed = voice.listen()
                    except RuntimeError as e:
                        console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                        continue

                    if not transcribed:
                        console.print("[dim]Didn't catch anything -- listening for the wake word again...[/dim]\n")
                        continue

                    console.print(f"[bold green]You (voice)[/bold green] \u203a {transcribed}")
                    handle_message(jarvis, voice, transcribed, speak_replies, session_log)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped listening for the wake word.[/dim]\n")
            except RuntimeError as e:
                console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                console.print()
            continue

        if lowered == "/voice" or lowered.startswith("/voice "):
            parts = stripped.split()
            duration = None
            if len(parts) == 2 and parts[1].isdigit():
                duration = int(parts[1])

            try:
                console.print("[dim]Listening...[/dim]")
                transcribed = voice.listen(duration) if duration else voice.listen()
            except RuntimeError as e:
                console.print(Panel(str(e), title="[bold red]Error[/bold red]", border_style="red", expand=False))
                console.print()
                continue

            if not transcribed:
                console.print("[dim]Didn't catch anything -- try again.[/dim]\n")
                continue

            console.print(f"[bold green]You (voice)[/bold green] \u203a {transcribed}")
            user_input = transcribed

        handle_message(jarvis, voice, user_input, speak_replies, session_log)
        console.print(Rule(style="dim"))


if __name__ == "__main__":
    main()
