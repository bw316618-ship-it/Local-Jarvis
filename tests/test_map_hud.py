"""tools/map_hud.py -- the browser-facing map action queue (clear/focus).

Note: place *search* used to be duplicated here as search_map_places,
with its own copy of CATEGORY_TAGS / the Overpass query builder /
haversine distance, overlapping tools/nearby.py's find_nearby_place.
That tool has been removed; searching is covered by
tests/test_nearby_and_routing.py. This file covers what's left:
queueing/draining actions, clearing markers, and focusing the map.
"""

import json

import tools.map_hud as mh


def setup_function(_):
    # _MAP_ACTIONS is a module-level queue; drain it before each test so
    # actions queued by one test can't leak into the next.
    mh.drain_map_actions()


def test_queue_action_returns_a_parseable_map_action_string():
    result = mh._queue_action("focus_marker", latitude=1.0, longitude=2.0)

    assert result.startswith("JARVIS_MAP_ACTION:")
    payload = json.loads(result[len("JARVIS_MAP_ACTION:"):])
    assert payload == {"action": "focus_marker", "latitude": 1.0, "longitude": 2.0}


def test_queue_action_is_also_pushed_to_the_drainable_queue():
    mh._queue_action("clear_markers", category="cafe")

    actions = mh.drain_map_actions()
    assert actions == [{"action": "clear_markers", "category": "cafe"}]


def test_drain_map_actions_empties_the_queue():
    mh._queue_action("clear_markers", category="")

    first_drain = mh.drain_map_actions()
    second_drain = mh.drain_map_actions()

    assert len(first_drain) == 1
    assert second_drain == []


def test_drain_map_actions_preserves_order():
    mh._queue_action("focus_marker", latitude=1.0, longitude=1.0)
    mh._queue_action("clear_markers", category="")
    mh._queue_action("focus_marker", latitude=2.0, longitude=2.0)

    actions = mh.drain_map_actions()

    assert [a["action"] for a in actions] == [
        "focus_marker",
        "clear_markers",
        "focus_marker",
    ]


def test_clear_map_markers_defaults_to_clearing_everything():
    mh.clear_map_markers()

    actions = mh.drain_map_actions()
    assert actions == [{"action": "clear_markers", "category": ""}]


def test_clear_map_markers_normalizes_category_casing_and_whitespace():
    mh.clear_map_markers("  Cafe  ")

    actions = mh.drain_map_actions()
    assert actions[0]["category"] == "cafe"


def test_focus_map_marker_defaults_zoom_and_clamps_to_valid_range():
    mh.focus_map_marker(latitude=51.5, longitude=-0.1, zoom=99)

    actions = mh.drain_map_actions()
    assert actions[0]["zoom"] == 20  # clamped down from 99


def test_focus_map_marker_clamps_low_zoom_too():
    mh.focus_map_marker(latitude=51.5, longitude=-0.1, zoom=-5)

    actions = mh.drain_map_actions()
    assert actions[0]["zoom"] == 1  # clamped up from -5


def test_focus_map_marker_coerces_coordinates_to_float():
    mh.focus_map_marker(latitude="51.5", longitude="-0.1")

    actions = mh.drain_map_actions()
    assert actions[0]["latitude"] == 51.5
    assert actions[0]["longitude"] == -0.1


def test_focus_map_marker_defaults_name_to_empty_string():
    mh.focus_map_marker(latitude=1.0, longitude=1.0)

    actions = mh.drain_map_actions()
    assert actions[0]["name"] == ""


def test_search_map_places_no_longer_exists_as_a_duplicate_tool():
    # Guards against reintroducing the duplicate Overpass-search tool;
    # find_nearby_place in tools/nearby.py is the single search entry
    # point now.
    assert not hasattr(mh, "search_map_places")
    assert "search_map_places" not in mh.MAP_HUD_TOOL_FUNCTIONS


def test_registered_schema_and_function_names_match():
    schema_names = {
        schema["function"]["name"] for schema in mh.MAP_HUD_TOOL_SCHEMAS
    }
    assert schema_names == set(mh.MAP_HUD_TOOL_FUNCTIONS.keys())
    assert schema_names == {"clear_map_markers", "focus_map_marker"}
