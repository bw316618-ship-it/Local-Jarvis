from rich.console import Console
from brain.llm import JarvisLLM

console = Console()


def main():
    console.print("[bold cyan]Jarvis is online[/bold cyan]")

    jarvis = JarvisLLM()

    while True:
        user_input = console.input("[bold green]You > [/bold green]")

        if user_input.lower() in ("exit", "quit"):
            break

        try:
            reply = jarvis.chat(user_input)
            console.print(f"[bold blue]Jarvis >[/bold blue] {reply}\n")
        except Exception as e:
            console.print(f"[bold red]{e}[/bold red]")


if __name__ == "__main__":
    main()