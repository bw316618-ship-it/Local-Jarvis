"""
System-control tools for Jarvis: running shell commands and launching
applications/files/URLs.

Every tool here is registered as "risky" in tools/tools.py -- Jarvis will
ask for confirmation before running any of them, since they can change
or affect things well beyond Jarvis's own sandbox.
"""

import os
import platform
import subprocess

COMMAND_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000


def run_command(command: str) -> str:
    """Run a shell command and return its combined stdout/stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds."
    except Exception as e:
        return f"Failed to run command: {e}"

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n[... output truncated ...]"

    status = f"(exit code {result.returncode})"
    return f"{output}\n{status}" if output else f"Command finished with no output. {status}"


def open_application(target: str) -> str:
    """Open an application, file, or URL using the OS's default handler."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(target)  # noqa: S606 -- intentional, this is the tool's whole job
        elif system == "Darwin":
            subprocess.run(["open", target], check=True)
        else:
            subprocess.run(["xdg-open", target], check=True)
        return f"Opened '{target}'."
    except Exception as e:
        return f"Could not open '{target}': {e}"


SYSTEM_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell/terminal command on the local machine and return "
                "its output. Use for anything not covered by a more specific "
                "tool -- installing packages, running scripts, checking system "
                "info, managing processes, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full command to run, exactly as you'd type it in a terminal.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": (
                "Open an application, file, or URL using its default handler "
                "(e.g. 'notepad', 'C:/Users/me/report.pdf', 'https://example.com')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Application name/path, file path, or URL to open.",
                    },
                },
                "required": ["target"],
            },
        },
    },
]

SYSTEM_TOOL_FUNCTIONS = {
    "run_command": run_command,
    "open_application": open_application,
}

SYSTEM_RISKY_TOOLS = {"run_command", "open_application"}
