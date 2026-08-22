"""Tests for the HUD "System Status" widget backend.

Previously the widget's frontend shell existed (index.html's empty
#inspectorDiagnostics container, inspector.js's diag-grid rendering) but
nothing on the backend ever pushed real data into it -- only
browser-side stats (JS heap, WebSocket connection state, device count)
were ever shown. This covers the two new pieces: tools/diagnostics.py's
structured snapshot, and ui/hud_server.py's periodic broadcast loop.

The broadcast loop is tested by driving its coroutine directly via
asyncio.run() rather than spinning up a real WebSocket server -- the
loop's own logic (broadcast, interruptible wait, exception containment)
is what's under test here, not the transport.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import ui.hud_server as hud_server_module
from tools.diagnostics import system_status, system_status_snapshot
from ui.hud_server import HUDBridge

EXPECTED_SNAPSHOT_KEYS = {
    "cpu_percent", "cpu_count",
    "memory_percent", "memory_used_bytes", "memory_total_bytes",
    "disk_percent", "disk_used_bytes", "disk_total_bytes",
    "uptime_seconds", "process_count",
}


# --- tools/diagnostics.py: the shared snapshot ----------------------------

def test_snapshot_has_all_expected_keys():
    snap = system_status_snapshot()
    assert EXPECTED_SNAPSHOT_KEYS <= set(snap)


def test_snapshot_values_are_sane_types_and_ranges():
    snap = system_status_snapshot()
    assert 0 <= snap["cpu_percent"] <= 100
    assert 0 <= snap["memory_percent"] <= 100
    assert 0 <= snap["disk_percent"] <= 100
    assert snap["cpu_count"] >= 1
    assert snap["memory_used_bytes"] <= snap["memory_total_bytes"]
    assert snap["disk_used_bytes"] <= snap["disk_total_bytes"]
    assert snap["uptime_seconds"] >= 0
    assert snap["process_count"] >= 1


def test_string_and_snapshot_share_one_underlying_read(monkeypatch):
    """system_status()'s chat-facing string and the HUD's snapshot must
    stay in sync by construction (one psutil read, two presentations) --
    not just coincidentally produce similar-looking numbers. Verified by
    patching the shared snapshot function and confirming the string
    output reflects the patched values exactly."""
    fake_snapshot = {
        "cpu_percent": 42.0, "cpu_count": 8,
        "memory_percent": 55.0, "memory_used_bytes": 4 * 1024 ** 3, "memory_total_bytes": 8 * 1024 ** 3,
        "disk_percent": 30.0, "disk_used_bytes": 100 * 1024 ** 3, "disk_total_bytes": 500 * 1024 ** 3,
        "uptime_seconds": 3725, "process_count": 250,
    }
    import tools.diagnostics as diagnostics_module
    monkeypatch.setattr(diagnostics_module, "system_status_snapshot", lambda: fake_snapshot)

    result = system_status()
    assert "CPU: 42% used (8 cores)" in result
    assert "Memory: 55% used" in result
    assert "4.0 GB / 8.0 GB" in result
    assert "Disk: 30% used" in result
    assert "100.0 GB / 500.0 GB" in result
    assert "Running processes: 250" in result


# --- ui/hud_server.py: the periodic broadcast loop -----------------------

def test_loop_broadcasts_a_system_status_message():
    bridge = HUDBridge()
    fake_snapshot = {"cpu_percent": 12.3, "process_count": 99}
    broadcasts = []

    async def fake_broadcast_json(payload):
        broadcasts.append(payload)

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "system_status_snapshot", return_value=fake_snapshot), \
             patch.object(bridge, "_broadcast_json", new=AsyncMock(side_effect=fake_broadcast_json)):
            task = asyncio.create_task(bridge._system_status_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())

    assert len(broadcasts) >= 1
    assert broadcasts[0]["type"] == "system_status"
    assert broadcasts[0]["cpu_percent"] == 12.3
    assert broadcasts[0]["process_count"] == 99


def test_loop_stops_promptly_even_with_a_long_interval(monkeypatch):
    """Proves the interruptible-wait design: this uses
    asyncio.wait_for(stop_signal.wait(), timeout=...) rather than a flat
    asyncio.sleep(...), specifically so setting the stop signal ends the
    loop almost immediately rather than after waiting out the full
    interval -- important since stop() is called on every HUD shutdown,
    and a 5+ second hang there would be a real, user-visible delay."""
    monkeypatch.setattr(hud_server_module, "SYSTEM_STATUS_INTERVAL_SECONDS", 999)

    bridge = HUDBridge()

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "system_status_snapshot", return_value={}), \
             patch.object(bridge, "_broadcast_json", new=AsyncMock()):
            task = asyncio.create_task(bridge._system_status_loop())
            await asyncio.sleep(0.05)
            start = time.monotonic()
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)
            return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed < 1.0


def test_loop_survives_a_broken_snapshot_function():
    """A psutil failure (permissions, unsupported platform call, etc.)
    must never take down the whole broadcast loop -- it should log and
    keep trying on the next tick, same fail-safe standard as
    brain/tool_relevance.py's filtering fallback."""
    bridge = HUDBridge()
    call_count = 0

    def broken_snapshot():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("psutil exploded")

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "system_status_snapshot", side_effect=broken_snapshot), \
             patch.object(bridge, "_broadcast_json", new=AsyncMock()):
            task = asyncio.create_task(bridge._system_status_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())  # must not raise
    assert call_count >= 1


def test_loop_broadcasts_nothing_when_no_devices_connected():
    """_broadcast_json already no-ops when self._devices is empty (see
    its own early return) -- confirms the loop doesn't need its own
    "is anyone listening" check, since it delegates that correctly."""
    bridge = HUDBridge()
    assert bridge._devices == {}

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "system_status_snapshot", return_value={}):
            task = asyncio.create_task(bridge._system_status_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())  # must not raise even with zero connected clients
