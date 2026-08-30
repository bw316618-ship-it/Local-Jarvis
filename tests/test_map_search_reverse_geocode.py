"""ui/hud_server.py's map_search / map_reverse_geocode WS message
handling -- the reverse channel added so the browser (a search box, a
map click) can ask for something instead of only ever receiving
LLM-tool-driven map_action broadcasts.

_handle_map_search / _handle_map_reverse_geocode are plain synchronous
methods (they run on a background thread spawned by _handle_incoming,
not on the asyncio loop -- same pattern as the existing
_handle_user_message), so they're tested directly by calling them and
mocking self._broadcast, rather than driving the async WS handler.

_handle_incoming's dispatch (that it spawns a thread for these message
types rather than blocking the event loop on network I/O) is tested
separately below via asyncio.run().
"""

import asyncio
from unittest.mock import MagicMock, patch

import ui.hud_server as hud_server_module
from ui.hud_server import HUDBridge


# --- _handle_map_search ---------------------------------------------------

def test_search_success_broadcasts_markers_then_result():
    bridge = HUDBridge()
    broadcasts = []

    fake_action = {"action": "add_marker", "name": "Cafe"}

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "find_nearby_place", return_value="Found 1 result."), \
         patch.object(hud_server_module, "drain_map_actions", return_value=[fake_action]):
        bridge._handle_map_search("coffee")

    types = [b["type"] for b in broadcasts]
    assert types == ["map_action", "map_search_result"]
    assert broadcasts[0]["action"] == "add_marker"
    assert broadcasts[1]["text"] == "Found 1 result."
    assert broadcasts[1]["query"] == "coffee"
    assert "error" not in broadcasts[1]


def test_search_passes_query_and_radius_through():
    bridge = HUDBridge()

    with patch.object(bridge, "_broadcast"), \
         patch.object(hud_server_module, "find_nearby_place", return_value="ok") as fake_find, \
         patch.object(hud_server_module, "drain_map_actions", return_value=[]):
        bridge._handle_map_search("pizza", 2.5)

    fake_find.assert_called_once_with("pizza", 2.5)


def test_search_failure_broadcasts_error_result_not_a_crash():
    bridge = HUDBridge()
    broadcasts = []

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "find_nearby_place", side_effect=RuntimeError("Overpass down")):
        bridge._handle_map_search("coffee")

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "map_search_result"
    assert broadcasts[0]["error"] is True
    assert "Overpass down" in broadcasts[0]["text"]


def test_search_with_no_results_still_broadcasts_a_result_message():
    """find_nearby_place returning a "no results" string (not an
    exception) is a normal, successful call -- must still reach the
    person as a map_search_result, not be swallowed."""
    bridge = HUDBridge()
    broadcasts = []

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "find_nearby_place", return_value="No results found for 'xyzzy'."), \
         patch.object(hud_server_module, "drain_map_actions", return_value=[]):
        bridge._handle_map_search("xyzzy")

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "map_search_result"
    assert "No results" in broadcasts[0]["text"]


# --- _handle_map_reverse_geocode ------------------------------------------

def test_reverse_geocode_success_broadcasts_marker():
    bridge = HUDBridge()
    broadcasts = []

    fake_marker = {"name": "A Cafe", "lat": 1.0, "lon": 2.0}

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "reverse_geocode_place", return_value=fake_marker):
        bridge._handle_map_reverse_geocode(1.0, 2.0)

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "map_reverse_geocode_result"
    assert broadcasts[0]["marker"] == fake_marker


def test_reverse_geocode_lookup_error_dict_is_passed_through():
    """reverse_geocode_place already returns {"error": ...} rather than
    raising on a normal lookup failure -- that dict must reach the
    frontend as-is."""
    bridge = HUDBridge()
    broadcasts = []

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "reverse_geocode_place", return_value={"error": "No address found."}):
        bridge._handle_map_reverse_geocode(1.0, 2.0)

    assert broadcasts[0]["marker"] == {"error": "No address found."}


def test_reverse_geocode_unexpected_exception_still_broadcasts_error():
    bridge = HUDBridge()
    broadcasts = []

    with patch.object(bridge, "_broadcast", side_effect=lambda p: broadcasts.append(p)), \
         patch.object(hud_server_module, "reverse_geocode_place", side_effect=RuntimeError("boom")):
        bridge._handle_map_reverse_geocode(1.0, 2.0)

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "map_reverse_geocode_result"
    assert "boom" in broadcasts[0]["marker"]["error"]


# --- _handle_incoming dispatch --------------------------------------------

def test_incoming_map_search_spawns_a_thread_not_a_blocking_call():
    """Overpass/Nominatim network I/O must not run on the asyncio event
    loop -- _handle_incoming should hand it off to a thread, same as
    the existing user_message handling, and return immediately."""
    bridge = HUDBridge()

    with patch.object(hud_server_module.threading, "Thread") as fake_thread_cls:
        fake_thread = MagicMock()
        fake_thread_cls.return_value = fake_thread

        asyncio.run(
            bridge._handle_incoming(
                MagicMock(),
                '{"type": "map_search", "query": "coffee"}',
            )
        )

    fake_thread_cls.assert_called_once()
    _, kwargs = fake_thread_cls.call_args
    assert kwargs["target"] == bridge._handle_map_search
    assert kwargs["args"] == ("coffee", None)
    fake_thread.start.assert_called_once()


def test_incoming_map_search_with_blank_query_does_nothing():
    bridge = HUDBridge()

    with patch.object(hud_server_module.threading, "Thread") as fake_thread_cls:
        asyncio.run(
            bridge._handle_incoming(
                MagicMock(),
                '{"type": "map_search", "query": "   "}',
            )
        )

    fake_thread_cls.assert_not_called()


def test_incoming_map_reverse_geocode_spawns_a_thread():
    bridge = HUDBridge()

    with patch.object(hud_server_module.threading, "Thread") as fake_thread_cls:
        fake_thread = MagicMock()
        fake_thread_cls.return_value = fake_thread

        asyncio.run(
            bridge._handle_incoming(
                MagicMock(),
                '{"type": "map_reverse_geocode", "lat": 1.5, "lon": 2.5}',
            )
        )

    fake_thread_cls.assert_called_once()
    _, kwargs = fake_thread_cls.call_args
    assert kwargs["target"] == bridge._handle_map_reverse_geocode
    assert kwargs["args"] == (1.5, 2.5)


def test_incoming_map_reverse_geocode_with_invalid_coordinates_does_nothing():
    bridge = HUDBridge()

    with patch.object(hud_server_module.threading, "Thread") as fake_thread_cls:
        asyncio.run(
            bridge._handle_incoming(
                MagicMock(),
                '{"type": "map_reverse_geocode", "lat": "not-a-number", "lon": 2.5}',
            )
        )

    fake_thread_cls.assert_not_called()
