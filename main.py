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
from voice import session_state
from voice.voice import JarvisVoice
from voice.wake_word import listen_for_wake_word

console = Console()

COMMANDS = [
    ("/help", "Show this command list"),
    ("/index", "Reindex configured folders for semantic file search"),
    ("/insights", "Check for proactive suggestions based on recent activity"),
    ("/status", "Show current CPU, memory, disk, and top processes"),
    ("/memory [category]", "List facts Jarvis has explicitly remembered"),
    ("/hud", "Toggle the graphical HUD"),
    ("/voice [N]", "Speak your message"),
    ("/wake", "Always-listening mode"),
    ("/speak on|off", "Toggle spoken replies"),
    ("/talk", "Toggle companion mode"),
    ("/creative [path]", "Enter creative mode, optionally selecting a story/PDF"),
    ("/creative-off", "Leave creative mode"),
    ("/project <name>", "Activate a named creative project"),
    ("/project", "Show the active creative project"),
    ("/coding [path]", "Enter coding mode, optionally targeting a repo/folder"),
    ("/coding-off", "Leave coding mode"),
    ("/save [path]", "Save this session's transcript"),
    ("/log [n]", "Show recent tool calls"),
    ("/forget", "Permanently clear long-term conversation memory"),
    ("exit / quit", "End the session"),
]


def show_insights(suggestions: list, title: str = "Noticed a few things") -> None:
    if not suggestions:
        console.print("[dim]Nothing stands out right now.[/dim]\n")
        return

    body = "\n\n".join(f"- {s}" for s in suggestions)

    console.print(
        Panel(
            body,
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan",
            expand=False,
        )
    )
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
    console.print(
        "[dim]Type[/dim] /help [dim]to see everything Jarvis can do.[/dim]\n"
    )


def print_help() -> None:
    table = Table(
        border_style="dim",
        show_header=True,
        header_style="bold cyan",
        expand=False,
    )
    table.add_column("Command")
    table.add_column("What it does")

    for cmd, desc in COMMANDS:
        table.add_row(cmd, desc)

    console.print(table)
    console.print(
        "[dim]Normal mode has full tool access. Companion mode is conversation-first. "
        "Creative mode scopes story feedback and brainstorming to the active document. "
        "Risky actions still require confirmation.[/dim]\n"
    )


def _handle_possible_session_end() -> bool:
    if not session_state.is_end_requested():
        return False

    session_state.clear_end_request()
    hud.stop()
    console.print("[dim]Goodbye.[/dim]")

    return True


def _switch_mode(new_mode: str) -> str | None:
    """Switch session mode, returning a notice string if leaving CREATIVE
    mode with an active document/project, or None otherwise.

    The scope itself isn't lost -- voice/document_state.py's active
    document/project persists independently of session mode and resumes
    automatically via /creative or whenever the model re-enters creative
    mode -- but silently switching away without any acknowledgment was a
    real gap. Originally only /talk warned about this; going straight
    from /creative to /coding (or the reverse) gave zero indication
    anything was being left behind. Every mode-switching command routes
    through this helper now, so the notice is consistent regardless of
    which command triggered the switch.

    CODING mode deliberately isn't covered by this -- it has no
    persistent state of its own (git_tools.py takes repo_path per call,
    nothing is "active" between turns), so there's nothing to warn about
    when leaving it.
    """
    from voice import document_state

    current = session_state.current_mode()
    project = document_state.get_active_project()
    document = document_state.get_active_document()
    leaving_creative_scope = (
        current == session_state.CREATIVE
        and new_mode != session_state.CREATIVE
        and (project or document)
    )

    notice = None
    if leaving_creative_scope:
        scope_desc = f"project {project!r}" if project else "the active document"
        notice = (
            f"Leaving creative mode -- {scope_desc} is still selected "
            "and will resume if you go back with /creative."
        )

    session_state.set_mode(new_mode)
    return notice


def _print_mode() -> None:
    mode = session_state.current_mode()

    labels = {
        session_state.NORMAL: "normal",
        session_state.COMPANION: "companion",
        session_state.CREATIVE: "creative",
        session_state.CODING: "coding",
    }

    console.print(f"[dim]Mode: {labels.get(mode, mode)}[/dim]\n")


# Short tag shown in the prompt for any non-NORMAL mode. A dict lookup
# rather than a chain of ternaries, so adding another mode later is one
# line here instead of another nested branch.
_PROMPT_MODE_TAGS = {
    session_state.COMPANION: "talking",
    session_state.CREATIVE: "creative",
    session_state.CODING: "coding",
}


def main():
    play_boot_animation()
    print_banner()

    jarvis = JarvisLLM(
        confirm_callback=make_confirm_callback(console=console)
    )

    voice = JarvisVoice()

    session = JarvisSession(
        jarvis,
        hud=hud,
        console=console,
        voice=voice,
        broadcast_text=False,
    )

    import threading

    threading.Thread(
        target=voice.warm_up,
        daemon=True,
    ).start()

    speak_replies = False
    session_log = []

    try:
        startup_suggestions = get_suggestions()

        if startup_suggestions:
            show_insights(
                startup_suggestions,
                title="Noticed a few things",
            )
    except Exception:
        pass

    try:
        pending = count_pending_changes()

        if pending:
            console.print(
                f"[dim]{pending} file(s) have changed since your last "
                "/index -- run /index to keep search results fresh.[/dim]\n"
            )
    except Exception:
        pass

    while True:
        mode = session_state.current_mode()
        tag = _PROMPT_MODE_TAGS.get(mode)
        prompt_label = (
            f"[bold green]You[/bold green] [dim]({tag})[/dim] [dim]›[/dim] "
            if tag
            else "[bold green]You[/bold green] [dim]›[/dim] "
        )

        user_input = console.input(prompt_label)
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

            console.print(
                Panel(
                    read_recent(n),
                    title="[bold cyan]Recent tool calls[/bold cyan]",
                    border_style="cyan",
                    expand=False,
                )
            )
            console.print()
            continue

        if lowered == "/insights":
            show_insights(get_suggestions(), title="Insights")
            continue

        if lowered == "/status":
            try:
                body = system_status() + "\n\n" + top_processes()

                console.print(
                    Panel(
                        body,
                        title="[bold cyan]System status[/bold cyan]",
                        border_style="cyan",
                        expand=False,
                    )
                )
            except Exception as e:
                console.print(
                    Panel(
                        str(e),
                        title="[bold red]Error[/bold red]",
                        border_style="red",
                        expand=False,
                    )
                )

            console.print()
            continue

        if lowered == "/memory" or lowered.startswith("/memory "):
            parts = stripped.split(maxsplit=1)
            category = parts[1] if len(parts) == 2 else None
            facts = list_facts(category)

            if facts:
                body = "\n".join(f"- {f}" for f in facts)
                title = (
                    f"Remembered facts"
                    f"{f' ({category})' if category else ''}"
                )

                console.print(
                    Panel(
                        body,
                        title=f"[bold cyan]{title}[/bold cyan]",
                        border_style="cyan",
                        expand=False,
                    )
                )
            else:
                console.print(
                    "[dim]Nothing remembered yet"
                    + (f" under '{category}'." if category else ".")
                    + "[/dim]"
                )

            console.print()
            continue

        if lowered == "/hud":
            if hud.is_running():
                hud.stop()
                console.print("[dim]Graphical HUD closed.[/dim]\n")
            else:
                started = hud.start(open_browser=True)

                if started:
                    console.print(
                        f"[dim]Graphical HUD opened at "
                        f"http://localhost:{hud.http_port} -- run /hud again "
                        "to close it.[/dim]\n"
                    )
                else:
                    console.print(
                        Panel(
                            "Could not start the HUD.",
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
                    "This permanently deletes everything Jarvis has learned "
                    "from past conversations across all sessions. It cannot "
                    "be undone.",
                    title="[bold yellow]Confirm[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
            )

            answer = console.input(
                "[bold yellow]Clear long-term memory?[/bold yellow] [y/N] > "
            ).strip().lower()

            if answer == "y":
                console.print(
                    f"[bold cyan]{forget_all()}[/bold cyan]\n"
                )
            else:
                console.print("[dim]Cancelled.[/dim]\n")

            continue

        if lowered == "/save" or lowered.startswith("/save "):
            parts = stripped.split(maxsplit=1)
            save_path = parts[1] if len(parts) == 2 else None

            result = save_transcript(
                session_log,
                path=save_path,
            )

            console.print(f"[bold cyan]{result}[/bold cyan]\n")
            continue

        if lowered in ("/speak on", "/speak off"):
            speak_replies = lowered == "/speak on"

            console.print(
                f"[dim]Spoken replies turned "
                f"{'on' if speak_replies else 'off'}.[/dim]\n"
            )
            continue

        if lowered.startswith("/speak"):
            console.print(
                "[dim]Usage: /speak on  or  /speak off[/dim]\n"
            )
            continue

        if lowered == "/talk":
            if session_state.current_mode() == session_state.COMPANION:
                _switch_mode(session_state.NORMAL)
                console.print(
                    "[dim]Companion mode off -- back to normal, "
                    "full tool access.[/dim]\n"
                )
            else:
                notice = _switch_mode(session_state.COMPANION)

                if notice:
                    console.print(
                        f"[dim]{notice} Companion mode on. "
                        "Say /talk again to leave.[/dim]\n"
                    )
                else:
                    console.print(
                        "[dim]Companion mode on -- conversation-first. "
                        "Say /talk again to leave.[/dim]\n"
                    )

            continue

        if lowered == "/creative-off":
            notice = _switch_mode(session_state.NORMAL)
            from voice import document_state

            document_state.clear_scope()
            if notice:
                # clear_scope() just wiped what the notice referred to --
                # /creative-off is an explicit, deliberate exit (unlike
                # /talk or /coding), so clearing scope here is correct,
                # but the notice's "will resume if you go back" promise
                # would be misleading in this specific case. Say so plainly
                # instead of reusing the generic notice text.
                console.print(
                    "[dim]Creative mode off -- back to normal task mode. "
                    "The active document/project selection was cleared.[/dim]\n"
                )
            else:
                console.print(
                    "[dim]Creative mode off -- back to normal task mode.[/dim]\n"
                )
            continue

        if lowered == "/creative" or lowered.startswith("/creative "):
            parts = stripped.split(maxsplit=1)

            _switch_mode(session_state.CREATIVE)

            if len(parts) == 2:
                from tools.creative_tools import set_creative_document

                result = set_creative_document(parts[1])
                console.print(f"[dim]{result}[/dim]\n")
            else:
                console.print(
                    "[dim]Creative mode on. No document is selected yet. "
                    "Jarvis can set one through the creative tools.[/dim]\n"
                )

            continue

        if lowered == "/project":
            from tools.creative_tools import get_creative_project

            _switch_mode(session_state.CREATIVE)
            console.print(f"[dim]{get_creative_project()}[/dim]\n")
            continue

        if lowered.startswith("/project "):
            from tools.creative_tools import set_creative_project

            project_name = stripped.split(maxsplit=1)[1]
            _switch_mode(session_state.CREATIVE)
            console.print(
                f"[dim]{set_creative_project(project_name)}[/dim]\n"
            )
            continue

        if lowered == "/coding-off":
            notice = _switch_mode(session_state.NORMAL)
            if notice:
                console.print(f"[dim]{notice} Coding mode off.[/dim]\n")
            else:
                console.print(
                    "[dim]Coding mode off -- back to normal task mode.[/dim]\n"
                )
            continue

        if lowered == "/coding" or lowered.startswith("/coding "):
            parts = stripped.split(maxsplit=1)

            notice = _switch_mode(session_state.CODING)
            if notice:
                console.print(f"[dim]{notice}[/dim]\n")

            if len(parts) == 2:
                from tools.git_tools import git_status

                console.print(
                    f"[dim]Coding mode on, targeting '{parts[1]}':[/dim]\n"
                    f"[dim]{git_status(parts[1])}[/dim]\n"
                )
            else:
                console.print(
                    "[dim]Coding mode on. Tell Jarvis which repo/folder "
                    "to work in, or it'll default to the current directory.[/dim]\n"
                )

            continue

        if lowered == "/index":
            console.print(
                "[dim]Indexing configured folders -- this can take a while "
                "the first time...[/dim]"
            )

            def show_progress(msg):
                console.print(f"[dim]  {msg}[/dim]")

            try:
                summary = index_files(progress=show_progress)
                console.print(
                    f"[bold cyan]{summary}[/bold cyan]\n"
                )
            except Exception as e:
                console.print(
                    Panel(
                        str(e),
                        title="[bold red]Indexing failed[/bold red]",
                        border_style="red",
                        expand=False,
                    )
                )
                console.print()

            continue

        if lowered == "/wake":
            console.print(
                '[dim]Listening for "Hey Jarvis"... (Ctrl+C to stop)[/dim]'
            )

            try:
                while True:
                    listen_for_wake_word()

                    console.print(
                        "[bold green]Jarvis (wake)[/bold green] › Yes?"
                    )

                    hud.set_state("listening")

                    try:
                        transcribed = voice.listen()
                    except RuntimeError as e:
                        hud.set_state("error")
                        console.print(
                            Panel(
                                str(e),
                                title="[bold red]Error[/bold red]",
                                border_style="red",
                                expand=False,
                            )
                        )
                        continue

                    if not transcribed:
                        hud.set_state("idle")
                        console.print(
                            "[dim]Didn't catch anything -- listening "
                            "for the wake word again...[/dim]\n"
                        )
                        continue

                    console.print(
                        f"[bold green]You (voice)[/bold green] › {transcribed}"
                    )

                    session.handle_message(
                        transcribed,
                        speak_replies,
                        session_log,
                    )

                    if _handle_possible_session_end():
                        return

            except KeyboardInterrupt:
                hud.set_state("idle")
                console.print(
                    "\n[dim]Stopped listening for the wake word.[/dim]\n"
                )
            except RuntimeError as e:
                hud.set_state("error")
                console.print(
                    Panel(
                        str(e),
                        title="[bold red]Error[/bold red]",
                        border_style="red",
                        expand=False,
                    )
                )
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
                transcribed = (
                    voice.listen(duration)
                    if duration
                    else voice.listen()
                )
            except RuntimeError as e:
                hud.set_state("error")
                console.print(
                    Panel(
                        str(e),
                        title="[bold red]Error[/bold red]",
                        border_style="red",
                        expand=False,
                    )
                )
                console.print()
                continue

            if not transcribed:
                hud.set_state("idle")
                console.print(
                    "[dim]Didn't catch anything -- try again.[/dim]\n"
                )
                continue

            console.print(
                f"[bold green]You (voice)[/bold green] › {transcribed}"
            )
            user_input = transcribed

        session.handle_message(
            user_input,
            speak_replies,
            session_log,
        )

        if _handle_possible_session_end():
            return

        console.print(Rule(style="dim"))


if __name__ == "__main__":
    main()
