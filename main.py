from rich.console import Console
from brain.llm import JarvisLLM
from voice.voice import JarvisVoice

console = Console()

HELP_TEXT = (
    "[dim]Commands: /voice (or /voice N) to speak your message instead of "
    "typing it, /speak on|off to toggle spoken replies, exit/quit to leave.[/dim]"
)


def main():
    console.print("[bold cyan]Jarvis is online[/bold cyan]")
    console.print(HELP_TEXT + "\n")

    jarvis = JarvisLLM()
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
