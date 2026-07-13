from rich.console import Console
from brain.llm import JarvisLLM
from voice.voice import JarvisVoice
from tools.file_index import index_files

console = Console()

HELP_TEXT = (
    "[dim]Jarvis can run commands, manage files anywhere, control your "
    "mouse/keyboard, open apps, search the web, and semantically search "
    "your indexed files -- it will ask before anything risky. Commands: "
    "/index to (re)index Documents/Desktop/Downloads for search, /voice "
    "(or /voice N) to speak your message, /speak on|off to toggle spoken "
    "replies, exit/quit to leave.[/dim]"
)


def confirm_tool_call(name: str, arguments: dict) -> bool:
    console.print(f"\n[bold yellow]Jarvis wants to run:[/bold yellow] {name}({arguments})")
    answer = console.input("[bold yellow]Allow this? [y/N] > [/bold yellow]").strip().lower()
    return answer == "y"


def main():
    console.print("[bold cyan]Jarvis is online[/bold cyan]")
    console.print(HELP_TEXT + "\n")

    jarvis = JarvisLLM(confirm_callback=confirm_tool_call)
    voice = JarvisVoice()
    speak_replies = False

    while True:
        user_input = console.input("[bold green]You > [/bold green]")
        stripped = user_input.strip()
        lowered = stripped.lower()

        if lowered in ("exit", "quit"):
            break

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
                console.print(f"[dim]{msg}[/dim]")

            try:
                summary = index_files(progress=show_progress)
                console.print(f"[bold cyan]{summary}[/bold cyan]\n")
            except Exception as e:
                console.print(f"[bold red]Indexing failed: {e}[/bold red]\n")
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
                console.print(f"[bold red]{e}[/bold red]\n")
                continue

            if not transcribed:
                console.print("[dim]Didn't catch anything -- try again.[/dim]\n")
                continue

            console.print(f"[bold green]You (voice) >[/bold green] {transcribed}")
            user_input = transcribed

        try:
            reply = jarvis.chat(user_input)
            console.print(f"[bold blue]Jarvis >[/bold blue] {reply}\n")
            if speak_replies:
                voice.speak(reply)
        except Exception as e:
            console.print(f"[bold red]{e}[/bold red]\n")


if __name__ == "__main__":
    main()
