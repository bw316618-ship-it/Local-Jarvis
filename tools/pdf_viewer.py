"""
PDF opening for Jarvis.

Delegates to the OS's default handler, the same approach
tools/system.py's open_application already uses -- a local PDF opens in
whatever the user's default PDF viewer is, a remote PDF URL opens in the
default browser, which every modern browser can render inline. This is a
thin, PDF-specific wrapper around that behavior rather than new opening
logic, so the model has a clearly-named tool for "open this PDF" instead
of overloading open_application's generic description.

An in-HUD embedded PDF viewer (rather than handing off to an external
app/browser) is a bigger, separate feature -- this only covers the
"just open the thing" case.

Risky for the same reason open_application is: it launches an external
application/browser outside Jarvis's own sandbox.
"""

import os
import platform
import subprocess
from pathlib import Path


def open_pdf(path_or_url: str) -> str:
    """Open a PDF, either a local file path or a URL, in the OS's default handler."""
    target = (path_or_url or "").strip()
    if not target:
        return "A file path or URL is required."

    is_url = target.lower().startswith(("http://", "https://"))

    if not is_url:
        local_path = Path(target).expanduser()
        if not local_path.exists():
            return f"'{target}' does not exist."
        if local_path.suffix.lower() != ".pdf":
            return f"'{target}' doesn't look like a PDF file (expected a .pdf extension)."
        target = str(local_path)

    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(target)  # noqa: S606 -- intentional, mirrors open_application
        elif system == "Darwin":
            subprocess.run(["open", target], check=True)
        else:
            subprocess.run(["xdg-open", target], check=True)
        return f"Opened '{target}'."
    except Exception as e:
        return f"Could not open '{target}': {e}"


PDF_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_pdf",
            "description": (
                "Open a PDF file -- either a local path or a URL -- in the user's "
                "default PDF viewer or browser."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path_or_url": {
                        "type": "string",
                        "description": "Local file path or URL to the PDF.",
                    },
                },
                "required": ["path_or_url"],
            },
        },
    },
]

PDF_TOOL_FUNCTIONS = {"open_pdf": open_pdf}

# Launches an external application/browser, same risk class as open_application.
PDF_RISKY_TOOLS = {"open_pdf"}
