"""HUD-native map controls.

These tools queue structured "map actions" that the HUD server forwards
to the browser over its websocket, where map_agent.js applies them to
the Leaflet map.

Searching for places is intentionally NOT done here -- that used to be
duplicated in this module (search_map_places, with its own copy of
CATEGORY_TAGS / the Overpass query builder / haversine distance). It is
now handled solely by tools/nearby.py's find_nearby_place, which is the
richer implementation: it auto-detects the current location, dedupes
and sorts results, returns a readable text summary to Jarvis, *and*
publishes the same markers to the map via _queue_action() below. Having
two tools that both search Overpass and both push markers made it
ambiguous which one the model would call, and search_map_places's own
result was just the raw map-action string with no summary for the user.
This module now only owns the map-only actions that find_nearby_place
doesn't cover: clearing pins and focusing the view.
"""

import json
import queue
import threading

_MAP_ACTIONS = queue.Queue()

# _MAP_ACTIONS is process-wide: every device's chat turn (via
# find_nearby_place, called as an LLM tool) and the HUD's own map search
# box / reverse-geocode-on-click feature (ui/hud_server.py's
# _handle_map_search) all enqueue onto and drain from this one queue.
# Without external synchronization, two producers racing (e.g. two
# search-box requests fired close together, or a search-box request
# overlapping a chat turn that happens to call find_nearby_place) can
# interleave: producer A enqueues, producer B enqueues and drains before
# A does, stealing A's action and leaving A's own drain call empty --
# so A's caller broadcasts a status-text result with no matching markers
# ever delivered. Worse, if a drain call runs at a moment where the
# queue happens to contain a stray leftover from an earlier race, that
# stale action gets broadcast attached to a completely unrelated later
# interaction. This showed up as "search only works once" / "results
# don't clear". MAP_ACTIONS_LOCK must be held by every caller for the
# full span from enqueue (i.e. the tool call that may enqueue actions)
# through its own drain_map_actions() call, so no other producer's
# actions can ever land inside another caller's drain.
MAP_ACTIONS_LOCK = threading.Lock()


def _queue_action(action, **payload):
    result = {"action": action, **payload}
    _MAP_ACTIONS.put(result)
    return "JARVIS_MAP_ACTION:" + json.dumps(result, separators=(",", ":"))


def drain_map_actions():
    """Return all pending browser-map actions.

    Callers that both produce actions (by calling a tool that may queue
    one, e.g. find_nearby_place) and then drain them to broadcast should
    hold MAP_ACTIONS_LOCK for the whole produce-then-drain span -- see
    the module docstring above for why.
    """
    actions = []
    while True:
        try:
            actions.append(_MAP_ACTIONS.get_nowait())
        except queue.Empty:
            return actions


def clear_map_markers(category: str = "") -> str:
    """Clear all map markers or one category."""
    return _queue_action("clear_markers", category=(category or "").strip().lower())


def focus_map_marker(latitude: float, longitude: float, zoom: int = 17, name: str = "") -> str:
    """Center the HUD map on a known location."""
    return _queue_action("focus_marker", latitude=float(latitude), longitude=float(longitude), zoom=max(1, min(int(zoom), 20)), name=name or "")


MAP_HUD_TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "clear_map_markers", "description": "Remove pins from the Jarvis map.", "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "focus_map_marker", "description": "Focus the Jarvis map on a known location.", "parameters": {"type": "object", "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}, "zoom": {"type": "integer"}, "name": {"type": "string"}}, "required": ["latitude", "longitude"]}}},
]
MAP_HUD_TOOL_FUNCTIONS = {"clear_map_markers": clear_map_markers, "focus_map_marker": focus_map_marker}
MAP_HUD_RISKY_TOOLS = set()
