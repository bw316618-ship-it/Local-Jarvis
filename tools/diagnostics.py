"""
Real-time diagnostics for Jarvis, via psutil.

Live system status, performance, and health at a glance: CPU, memory,
disk, uptime, and top processes. Everything here is read-only (looking at
system stats never changes anything), so none of it is registered as
risky.
"""

from datetime import datetime, timedelta

import psutil

TOP_PROCESS_COUNT = 5


def _format_bytes_gb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def system_status() -> str:
    """Return a snapshot of CPU, memory, disk, and uptime."""
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count()

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    uptime = timedelta(seconds=int(datetime.now().timestamp() - psutil.boot_time()))

    lines = [
        f"CPU: {cpu_percent:.0f}% used ({cpu_count} cores)",
        f"Memory: {mem.percent:.0f}% used ({_format_bytes_gb(mem.used)} / {_format_bytes_gb(mem.total)})",
        f"Disk: {disk.percent:.0f}% used ({_format_bytes_gb(disk.used)} / {_format_bytes_gb(disk.total)})",
        f"Uptime: {uptime}",
        f"Running processes: {len(psutil.pids())}",
    ]
    return "\n".join(lines)


def top_processes(by: str = "memory", count: int = TOP_PROCESS_COUNT) -> str:
    """List the top processes by memory or CPU usage."""
    by = by.strip().lower()
    if by not in ("memory", "cpu"):
        by = "memory"
    key = "memory_percent" if by == "memory" else "cpu_percent"

    # Priming call: cpu_percent needs a first call per-process to start
    # measuring, since it reports usage *since the last call*, not an
    # instantaneous value -- otherwise every process would show 0.0%.
    if by == "cpu":
        for p in psutil.process_iter(["pid"]):
            try:
                p.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        psutil.cpu_percent(interval=0.3)  # let the sampling window elapse

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs.sort(key=lambda info: info.get(key) or 0, reverse=True)
    top = procs[:count]

    if not top:
        return "Could not read process information."

    label = "memory %" if by == "memory" else "CPU %"
    lines = [f"Top {len(top)} processes by {label}:"]
    for p in top:
        value = p.get(key) or 0
        lines.append(f"- {p.get('name', '?')} (pid {p.get('pid')}): {value:.1f}%")
    return "\n".join(lines)


DIAGNOSTICS_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "system_status",
            "description": "Get a snapshot of current CPU, memory, disk usage, and system uptime.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_processes",
            "description": "List the top processes currently running, sorted by memory or CPU usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "by": {"type": "string", "description": "'memory' or 'cpu'. Defaults to memory."},
                    "count": {"type": "integer", "description": "How many processes to show. Defaults to 5."},
                },
                "required": [],
            },
        },
    },
]

DIAGNOSTICS_TOOL_FUNCTIONS = {
    "system_status": system_status,
    "top_processes": top_processes,
}

# Read-only -- looking at system stats never changes anything.
DIAGNOSTICS_RISKY_TOOLS = set()
