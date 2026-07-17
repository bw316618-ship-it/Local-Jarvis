"""
Conversation transcript export for Jarvis.

This is deliberately separate from long-term memory: Jarvis doesn't
remember past sessions (or even earlier turns within the same session --
each chat() call in brain/llm.py starts fresh aside from RAG/file-search
context), so this only captures what was said in the *current* session for
you to keep, not something Jarvis itself will read back later. Saving a
transcript here doesn't make Jarvis remember it next time you run it.

Transcripts are saved as Markdown under transcripts/ (gitignored) so they
render nicely if you open them anywhere.
"""

from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"


def append_turn(session_log: list, role: str, content: str) -> None:
    """Record one turn (role is 'user' or 'jarvis') in the in-memory session log."""
    session_log.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    })


def save_transcript(session_log: list, path: str = None) -> str:
    """Write the session log to a Markdown file and return the path saved to."""
    if not session_log:
        return "Nothing to save yet -- the conversation is still empty."

    if path:
        target = Path(path).expanduser()
    else:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = TRANSCRIPTS_DIR / f"session_{stamp}.md"

    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# Jarvis session -- {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for turn in session_log:
        speaker = "**You**" if turn["role"] == "user" else "**Jarvis**"
        lines.append(f"{speaker}: {turn['content']}")
        lines.append("")

    try:
        target.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        return f"Could not save transcript: {e}"

    return str(target)
