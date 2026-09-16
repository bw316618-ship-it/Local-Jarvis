"""ui/hud_server.py's proactive-insights broadcast loop.

memory/insights.py's get_suggestions() used to be checked only on
demand (/insights) or once at startup -- never unprompted while the
HUD was actually running. This is the periodic half: re-run
get_suggestions() every PROACTIVE_INSIGHTS_INTERVAL_SECONDS and
broadcast anything not already shown.

Tested the same way tests/test_hud_system_status.py tests
_system_status_loop: driving the coroutine directly via asyncio.run()
rather than spinning up a real WebSocket server, so what's under test
is the loop's own logic (dedup, interruptible wait, exception
containment) rather than the transport.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import ui.hud_server as hud_server_module
from ui.hud_server import HUDBridge


def test_loop_broadcasts_new_suggestions():
    bridge = HUDBridge()

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(
            hud_server_module, "get_suggestions", return_value=["you keep retrying the same failing command"]
        ), patch.object(bridge, "_broadcast_json", new=AsyncMock()) as broadcast:
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)
            return broadcast

    broadcast = asyncio.run(run())

    broadcast.assert_called_once_with(
        {"type": "proactive_note", "text": "you keep retrying the same failing command"}
    )


def test_loop_does_not_rebroadcast_the_same_suggestion_twice():
    """get_suggestions() re-derives its findings from the audit log
    every call -- without dedup against the previous check, the same
    still-true suggestion would get pushed again every single interval."""
    bridge = HUDBridge()
    bridge._last_proactive_suggestions = ["an old, already-shown suggestion"]

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(
            hud_server_module, "get_suggestions", return_value=["an old, already-shown suggestion"]
        ), patch.object(bridge, "_broadcast_json", new=AsyncMock()) as broadcast:
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)
            return broadcast

    broadcast = asyncio.run(run())

    broadcast.assert_not_called()


def test_loop_broadcasts_only_the_new_suggestion_among_several():
    bridge = HUDBridge()
    bridge._last_proactive_suggestions = ["already shown"]

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(
            hud_server_module, "get_suggestions", return_value=["already shown", "brand new one"]
        ), patch.object(bridge, "_broadcast_json", new=AsyncMock()) as broadcast:
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)
            return broadcast

    broadcast = asyncio.run(run())

    broadcast.assert_called_once_with({"type": "proactive_note", "text": "brand new one"})


def test_loop_stops_promptly_even_with_a_long_interval(monkeypatch):
    """Same interruptible-wait design as _system_status_loop: setting
    the stop signal must end the loop almost immediately, not after
    waiting out the full (here, 20-minute-by-default) interval."""
    monkeypatch.setattr(hud_server_module, "PROACTIVE_INSIGHTS_INTERVAL_SECONDS", 999)

    bridge = HUDBridge()

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "get_suggestions", return_value=[]), \
             patch.object(bridge, "_broadcast_json", new=AsyncMock()):
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            start = time.monotonic()
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)
            return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed < 1.0


def test_loop_survives_a_broken_get_suggestions():
    """A get_suggestions() failure (audit log corrupted, embedding
    model unavailable, etc.) must never take down the whole broadcast
    loop -- same fail-safe standard as the system-status loop."""
    bridge = HUDBridge()
    call_count = 0

    def broken_get_suggestions(include_folder_check=True):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("audit log corrupted")

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "get_suggestions", side_effect=broken_get_suggestions), \
             patch.object(bridge, "_broadcast_json", new=AsyncMock()):
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())  # must not raise
    assert call_count >= 1


def test_loop_broadcasts_nothing_when_no_devices_connected():
    """_broadcast_json already no-ops when self._devices is empty --
    confirms the loop doesn't need its own "is anyone listening" check
    beyond the dedup, since it delegates that correctly."""
    bridge = HUDBridge()
    assert bridge._devices == {}

    async def run():
        bridge._ws_stop_signal = asyncio.Event()
        with patch.object(hud_server_module, "get_suggestions", return_value=["something new"]):
            task = asyncio.create_task(bridge._proactive_insights_loop())
            await asyncio.sleep(0.05)
            bridge._ws_stop_signal.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())  # must not raise even with zero connected clients
