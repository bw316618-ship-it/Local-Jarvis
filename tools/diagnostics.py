"""
Real-time diagnostics for Jarvis, via psutil.

Live system status, performance, and health at a glance: CPU, memory,
disk, uptime, top processes, and battery level. Everything here is
read-only (looking at system stats never changes anything), so none of
it is registered as risky.
"""

from datetime import datetime, timedelta

import psutil

TOP_PROCESS_COUNT = 5


def _format_bytes_gb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def system_status_snapshot() -> dict:
    """Structured CPU/memory/disk/uptime snapshot.

    This is the shared data source behind both system_status()'s
    chat-facing string below and ui/hud_server.py's live "System Status"
    HUD widget -- one psutil read, two presentations, so the two never
    drift out of sync with each other. Memory/disk are kept in raw bytes
    here (not pre-converted to GB) so a consumer can pick its own display
    units rather than being locked into this module's formatting choice.
    """
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count()

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    uptime_seconds = int(datetime.now().timestamp() - psutil.boot_time())

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "memory_percent": mem.percent,
        "memory_used_bytes": mem.used,
        "memory_total_bytes": mem.total,
        "disk_percent": disk.percent,
        "disk_used_bytes": disk.used,
        "disk_total_bytes": disk.total,
        "uptime_seconds": uptime_seconds,
        "process_count": len(psutil.pids()),
    }


def system_status() -> str:
    """Return a snapshot of CPU, memory, disk, and uptime."""
    snap = system_status_snapshot()
    uptime = timedelta(seconds=snap["uptime_seconds"])

    lines = [
        f"CPU: {snap['cpu_percent']:.0f}% used ({snap['cpu_count']} cores)",
        f"Memory: {snap['memory_percent']:.0f}% used "
        f"({_format_bytes_gb(snap['memory_used_bytes'])} / {_format_bytes_gb(snap['memory_total_bytes'])})",
        f"Disk: {snap['disk_percent']:.0f}% used "
        f"({_format_bytes_gb(snap['disk_used_bytes'])} / {_format_bytes_gb(snap['disk_total_bytes'])})",
        f"Uptime: {uptime}",
        f"Running processes: {snap['process_count']}",
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


def battery_status() -> str:
    """Return battery percentage and charging status, if a battery is present.

    psutil.sensors_battery() returns None on desktops with no battery
    (and on some platforms/kernels without the right sensors exposed) --
    that's a normal case here, not an error, so it's reported plainly
    rather than raised.
    """
    battery = psutil.sensors_battery()
    if battery is None:
        return "No battery detected -- this machine may be a desktop with no battery, or battery info isn't exposed on this platform."

    plugged = "plugged in" if battery.power_plugged else "on battery"

    if not battery.power_plugged and battery.secsleft not in (
        psutil.POWER_TIME_UNLIMITED,
        psutil.POWER_TIME_UNKNOWN,
    ):
        remaining = str(timedelta(seconds=battery.secsleft))
        return f"{battery.percent:.0f}% -- {plugged} -- {remaining} remaining"

    return f"{battery.percent:.0f}% -- {plugged}"


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
    {
        "type": "function",
        "function": {
            "name": "get_battery_level",
            "description": "Get the current battery percentage and charging status, if this machine has a battery.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

DIAGNOSTICS_TOOL_FUNCTIONS = {
    "system_status": system_status,
    "top_processes": top_processes,
    "get_battery_level": battery_status,
}

# Read-only -- looking at system stats never changes anything.
DIAGNOSTICS_RISKY_TOOLS = set()
