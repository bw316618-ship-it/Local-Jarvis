from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import psutil


TOP_PROCESS_COUNT = 5


_last_network = None
_last_network_time = None


def _format_bytes_gb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _gpu_snapshot() -> dict:
    """
    Read NVIDIA GPU telemetry through nvidia-smi.

    If NVIDIA tooling is unavailable, return an empty result rather
    than making GPU telemetry failure break the entire system snapshot.
    """

    executable = shutil.which("nvidia-smi")

    if not executable:
        return {
            "available": False,
        }

    command = [
        executable,

        "--query-gpu="
        "name,"
        "utilization.gpu,"
        "utilization.memory,"
        "memory.used,"
        "memory.total,"
        "temperature.gpu,"
        "power.draw",

        "--format=csv,noheader,nounits",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            ),
            check=False,
        )

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return {
            "available": False,
        }

    if result.returncode != 0:
        return {
            "available": False,
        }

    line = (
        result.stdout
        or ""
    ).strip().splitlines()

    if not line:
        return {
            "available": False,
        }

    fields = [
        item.strip()
        for item in line[0].split(",")
    ]

    if len(fields) < 7:
        return {
            "available": False,
        }

    return {
        "available": True,

        "name": fields[0],

        "gpu_percent":
            _safe_float(fields[1]),

        "memory_percent":
            _safe_float(fields[2]),

        "memory_used_mb":
            _safe_float(fields[3]),

        "memory_total_mb":
            _safe_float(fields[4]),

        "temperature_c":
            _safe_float(fields[5]),

        "power_w":
            _safe_float(fields[6]),
    }


def _temperature_snapshot() -> dict:
    """
    Try to obtain CPU/system temperatures.

    Windows commonly does not expose these through psutil, so missing
    sensors are represented as unavailable instead of guessed.
    """

    try:
        temperatures = (
            psutil.sensors_temperatures()
        )
    except (
        AttributeError,
        NotImplementedError,
        OSError,
    ):
        return {
            "available": False,
        }

    if not temperatures:
        return {
            "available": False,
        }

    candidates = []

    preferred_names = (
        "coretemp",
        "k10temp",
        "cpu_thermal",
        "acpitz",
        "zenpower",
    )

    for name, entries in temperatures.items():
        priority = (
            0
            if name.lower()
            in preferred_names
            else 1
        )

        for entry in entries:
            current = getattr(
                entry,
                "current",
                None,
            )

            if current is None:
                continue

            candidates.append(
                (
                    priority,
                    float(current),
                    name,
                )
            )

    if not candidates:
        return {
            "available": False,
        }

    candidates.sort(
        key=lambda item: (
            item[0],
            -item[1],
        )
    )

    _, temperature, sensor = (
        candidates[0]
    )

    return {
        "available": True,
        "temperature_c": temperature,
        "sensor": sensor,
    }


def _network_snapshot() -> dict:
    """
    Return current network throughput.

    Throughput is calculated from the difference between consecutive
    snapshots. The first snapshot intentionally reports zero because
    there is no previous sample.
    """

    global _last_network
    global _last_network_time

    current = psutil.net_io_counters()

    now = time.monotonic()

    if (
        _last_network is None
        or _last_network_time is None
    ):
        _last_network = current
        _last_network_time = now

        return {
            "available": True,

            "bytes_sent": current.bytes_sent,
            "bytes_recv": current.bytes_recv,

            "upload_bps": 0,
            "download_bps": 0,
        }

    elapsed = max(
        now - _last_network_time,
        0.001,
    )

    upload_bps = max(
        0,
        current.bytes_sent
        - _last_network.bytes_sent,
    ) / elapsed

    download_bps = max(
        0,
        current.bytes_recv
        - _last_network.bytes_recv,
    ) / elapsed

    _last_network = current
    _last_network_time = now

    return {
        "available": True,

        "bytes_sent": current.bytes_sent,
        "bytes_recv": current.bytes_recv,

        "upload_bps": upload_bps,
        "download_bps": download_bps,
    }


def _workspace_snapshot() -> dict:
    """
    Describe the process workspace.

    Git information is optional. A non-Git directory is still a valid
    workspace and is reported as such.
    """

    cwd = Path.cwd()

    workspace = {
        "path": str(cwd),
        "name": cwd.name or str(cwd),
        "git": False,
        "branch": None,
        "dirty": None,
        "changed_files": None,
    }

    git = shutil.which("git")

    if not git:
        return workspace

    try:
        root_result = subprocess.run(
            [
                git,
                "-C",
                str(cwd),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            ),
            check=False,
        )

        if root_result.returncode != 0:
            return workspace

        workspace["git"] = True

        branch_result = subprocess.run(
            [
                git,
                "-C",
                str(cwd),
                "branch",
                "--show-current",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            ),
            check=False,
        )

        branch = (
            branch_result.stdout
            or ""
        ).strip()

        workspace["branch"] = (
            branch or "DETACHED"
        )

        status_result = subprocess.run(
            [
                git,
                "-C",
                str(cwd),
                "status",
                "--porcelain",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0
            ),
            check=False,
        )

        changed = [
            line
            for line in (
                status_result.stdout
                or ""
            ).splitlines()
            if line.strip()
        ]

        workspace["changed_files"] = (
            len(changed)
        )

        workspace["dirty"] = bool(
            changed
        )

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        pass

    return workspace


def system_status_snapshot() -> dict:
    """
    Return a complete structured telemetry snapshot.

    This is consumed by the HUD server and remains the single
    authoritative source for live Inspector system telemetry.
    """

    cpu_percent = (
        psutil.cpu_percent(
            interval=0.5
        )
    )

    cpu_count = (
        psutil.cpu_count()
    )

    memory = (
        psutil.virtual_memory()
    )

    drive = (
        Path.cwd().anchor
        or os.environ.get(
            "SystemDrive",
            "/",
        )
    )

    try:
        disk = psutil.disk_usage(
            drive
        )
    except OSError:
        disk = psutil.disk_usage(
            "/"
        )

    uptime_seconds = int(
        time.time()
        - psutil.boot_time()
    )

    battery = None

    try:
        battery = (
            psutil.sensors_battery()
        )
    except (
        AttributeError,
        NotImplementedError,
    ):
        battery = None

    battery_data = {
        "available": battery is not None,
    }

    if battery is not None:
        battery_data.update(
            {
                "percent":
                    float(
                        battery.percent
                    ),

                "plugged":
                    bool(
                        battery.power_plugged
                    ),

                "seconds_left":
                    (
                        None
                        if battery.secsleft
                        in (
                            psutil.POWER_TIME_UNKNOWN,
                            psutil.POWER_TIME_UNLIMITED,
                        )
                        else int(
                            battery.secsleft
                        )
                    ),
            }
        )

    return {
        # Core
        "cpu_percent":
            cpu_percent,

        "cpu_count":
            cpu_count,

        # Memory
        "memory_percent":
            memory.percent,

        "memory_used_bytes":
            memory.used,

        "memory_total_bytes":
            memory.total,

        # Disk
        "disk_percent":
            disk.percent,

        "disk_used_bytes":
            disk.used,

        "disk_total_bytes":
            disk.total,

        # Runtime
        "uptime_seconds":
            uptime_seconds,

        "process_count":
            len(psutil.pids()),

        # Hardware
        "gpu":
            _gpu_snapshot(),

        "temperature":
            _temperature_snapshot(),

        "battery":
            battery_data,

        # Network
        "network":
            _network_snapshot(),

        # Workspace
        "workspace":
            _workspace_snapshot(),

        "timestamp":
            time.time(),
    }


def system_status() -> str:
    """Return a human-readable system snapshot."""

    snap = system_status_snapshot()

    uptime = timedelta(
        seconds=snap[
            "uptime_seconds"
        ]
    )

    lines = [
        (
            f"CPU: "
            f"{snap['cpu_percent']:.0f}% used "
            f"({snap['cpu_count']} cores)"
        ),

        (
            f"Memory: "
            f"{snap['memory_percent']:.0f}% used "
            f"("
            f"{_format_bytes_gb(snap['memory_used_bytes'])}"
            f" / "
            f"{_format_bytes_gb(snap['memory_total_bytes'])}"
            f")"
        ),

        (
            f"Disk: "
            f"{snap['disk_percent']:.0f}% used "
            f"("
            f"{_format_bytes_gb(snap['disk_used_bytes'])}"
            f" / "
            f"{_format_bytes_gb(snap['disk_total_bytes'])}"
            f")"
        ),

        f"Uptime: {uptime}",

        (
            f"Running processes: "
            f"{snap['process_count']}"
        ),
    ]

    gpu = snap.get(
        "gpu",
        {"available": False},
    )

    if gpu.get("available"):
        lines.append(
            (
                f"GPU: "
                f"{gpu['name']} "
                f"{gpu['gpu_percent']:.0f}%"
            )
        )

        lines.append(
            (
                f"VRAM: "
                f"{gpu['memory_used_mb']:.0f} / "
                f"{gpu['memory_total_mb']:.0f} MB"
            )
        )

    battery = snap.get(
        "battery",
        {"available": False},
    )

    if battery.get("available"):
        lines.append(
            (
                f"Battery: "
                f"{battery['percent']:.0f}%"
            )
        )

    return "\n".join(lines)


def top_processes(
    by: str = "memory",
    count: int = TOP_PROCESS_COUNT,
) -> str:
    """List the top running processes."""

    by = (
        by.strip().lower()
        if isinstance(by, str)
        else "memory"
    )

    if by not in (
        "memory",
        "cpu",
    ):
        by = "memory"

    try:
        count = max(
            1,
            min(
                int(count),
                20,
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        count = TOP_PROCESS_COUNT

    key = (
        "memory_percent"
        if by == "memory"
        else "cpu_percent"
    )

    if by == "cpu":
        for process in psutil.process_iter(
            ["pid"]
        ):
            try:
                process.cpu_percent()
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                continue

        time.sleep(0.3)

    processes = []

    for process in psutil.process_iter(
        [
            "pid",
            "name",
            "memory_percent",
            "cpu_percent",
        ]
    ):
        try:
            processes.append(
                process.info
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            continue

    processes.sort(
        key=lambda info:
            info.get(key) or 0,
        reverse=True,
    )

    top = processes[:count]

    if not top:
        return (
            "Could not read process "
            "information."
        )

    label = (
        "memory %"
        if by == "memory"
        else "CPU %"
    )

    lines = [
        (
            f"Top {len(top)} processes "
            f"by {label}:"
        )
    ]

    for process in top:
        value = (
            process.get(key) or 0
        )

        lines.append(
            (
                f"- "
                f"{process.get('name', '?')} "
                f"(pid {process.get('pid')}): "
                f"{value:.1f}%"
            )
        )

    return "\n".join(lines)


def battery_status() -> str:
    """Return battery state."""

    battery = (
        psutil.sensors_battery()
    )

    if battery is None:
        return (
            "No battery detected."
        )

    plugged = (
        "plugged in"
        if battery.power_plugged
        else "on battery"
    )

    if (
        not battery.power_plugged
        and battery.secsleft not in (
            psutil.POWER_TIME_UNLIMITED,
            psutil.POWER_TIME_UNKNOWN,
        )
    ):
        remaining = str(
            timedelta(
                seconds=battery.secsleft
            )
        )

        return (
            f"{battery.percent:.0f}% "
            f"-- {plugged} "
            f"-- {remaining} remaining"
        )

    return (
        f"{battery.percent:.0f}% "
        f"-- {plugged}"
    )


DIAGNOSTICS_TOOL_SCHEMAS = [
    {
        "type": "function",

        "function": {
            "name":
                "system_status",

            "description":
                (
                    "Get current CPU, memory, "
                    "disk, uptime, GPU, battery "
                    "and basic system telemetry."
                ),

            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    {
        "type": "function",

        "function": {
            "name":
                "top_processes",

            "description":
                (
                    "List the top running "
                    "processes by CPU or memory."
                ),

            "parameters": {
                "type": "object",

                "properties": {
                    "by": {
                        "type": "string",
                        "description":
                            (
                                "'memory' "
                                "or 'cpu'."
                            ),
                    },

                    "count": {
                        "type": "integer",
                        "description":
                            (
                                "Number of "
                                "processes."
                            ),
                    },
                },

                "required": [],
            },
        },
    },

    {
        "type": "function",

        "function": {
            "name":
                "get_battery_level",

            "description":
                (
                    "Get current battery "
                    "percentage and charging "
                    "state."
                ),

            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


DIAGNOSTICS_TOOL_FUNCTIONS = {
    "system_status":
        system_status,

    "top_processes":
        top_processes,

    "get_battery_level":
        battery_status,
}


DIAGNOSTICS_RISKY_TOOLS = set()
