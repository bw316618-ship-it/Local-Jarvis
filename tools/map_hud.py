"""HUD-native map tools.

The tools return structured map actions. The HUD server forwards those
actions to the browser, where the map UI renders them.
"""

import json
import math
import queue

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REQUEST_TIMEOUT_SECONDS = 20
HEADERS = {
    "User-Agent": "Local-Jarvis/1.0 (personal local-first AI assistant)",
    "Accept": "application/json",
}
DEFAULT_RADIUS_KM = 2.0
MAX_RADIUS_KM = 25.0
DEFAULT_LIMIT = 30
MAX_LIMIT = 50
_MAP_ACTIONS = queue.Queue()

CATEGORY_TAGS = {
    "cafe": [("amenity", "cafe")], "cafes": [("amenity", "cafe")],
    "coffee shop": [("amenity", "cafe")], "coffee shops": [("amenity", "cafe")],
    "restaurant": [("amenity", "restaurant")], "restaurants": [("amenity", "restaurant")],
    "bar": [("amenity", "bar")], "bars": [("amenity", "bar")],
    "pharmacy": [("amenity", "pharmacy")], "hospital": [("amenity", "hospital")],
    "atm": [("amenity", "atm")], "bank": [("amenity", "bank")],
    "supermarket": [("shop", "supermarket")],
    "grocery": [("shop", "supermarket"), ("shop", "convenience")],
    "grocery store": [("shop", "supermarket"), ("shop", "convenience")],
    "hotel": [("tourism", "hotel")], "park": [("leisure", "park")],
    "library": [("amenity", "library")], "museum": [("tourism", "museum")],
    "gallery": [("tourism", "gallery")], "gas station": [("amenity", "fuel")],
    "petrol station": [("amenity", "fuel")], "parking": [("amenity", "parking")],
    "bus stop": [("highway", "bus_stop")], "train station": [("railway", "station")],
    "metro station": [("railway", "station"), ("station", "subway"), ("railway", "subway_entrance")],
    "subway station": [("railway", "station"), ("station", "subway"), ("railway", "subway_entrance")],
    "tourist attraction": [("tourism", "attraction"), ("tourism", "museum"), ("tourism", "gallery"), ("tourism", "zoo"), ("tourism", "theme_park"), ("historic", "monument"), ("historic", "memorial"), ("historic", "castle")],
    "attractions": [("tourism", "attraction"), ("tourism", "museum"), ("tourism", "gallery"), ("tourism", "zoo"), ("tourism", "theme_park"), ("historic", "monument"), ("historic", "memorial"), ("historic", "castle")],
}


def _haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _build_query(lat, lon, radius_m, filters):
    clauses = []
    for key, value in filters:
        for element_type in ("node", "way", "relation"):
            clauses.append(f'{element_type}["{key}"="{value}"](around:{radius_m},{lat},{lon});')
    return f"[out:json][timeout:{REQUEST_TIMEOUT_SECONDS}];\n(\n" + "\n".join(f"  {clause}" for clause in clauses) + "\n);\nout center;"


def _queue_action(action, **payload):
    result = {"action": action, **payload}
    _MAP_ACTIONS.put(result)
    return "JARVIS_MAP_ACTION:" + json.dumps(result, separators=(",", ":"))


def drain_map_actions():
    """Return all pending browser-map actions."""
    actions = []
    while True:
        try:
            actions.append(_MAP_ACTIONS.get_nowait())
        except queue.Empty:
            return actions


def search_map_places(category: str, latitude: float, longitude: float, radius_km: float = DEFAULT_RADIUS_KM, limit: int = DEFAULT_LIMIT) -> str:
    """Search real nearby places and pin them on the Jarvis HUD map."""
    category_key = (category or "").strip().lower()
    if not category_key:
        return "A place category is required."
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return "A valid latitude and longitude are required."
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "Latitude or longitude is outside the valid range."
    try:
        radius = max(0.1, min(float(radius_km), MAX_RADIUS_KM))
    except (TypeError, ValueError):
        radius = DEFAULT_RADIUS_KM
    try:
        result_limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        result_limit = DEFAULT_LIMIT
    query = _build_query(lat, lon, int(radius * 1000), CATEGORY_TAGS.get(category_key, [("amenity", category_key)]))
    try:
        response = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"Map place search failed: {exc}"
    except ValueError:
        return "Map place search failed: Overpass returned invalid JSON."

    markers = []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name")
        center = element.get("center") or {}
        marker_lat = element.get("lat", center.get("lat"))
        marker_lon = element.get("lon", center.get("lon"))
        if not name or marker_lat is None or marker_lon is None:
            continue
        marker_lat, marker_lon = float(marker_lat), float(marker_lon)
        markers.append({
            "id": f"{element.get('type', 'x')}-{element.get('id', '0')}",
            "name": name, "lat": marker_lat, "lon": marker_lon,
            "distance_km": _haversine_km(lat, lon, marker_lat, marker_lon),
            "category": category_key,
            "address": ", ".join(part for part in (tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city")) if part),
            "opening_hours": tags.get("opening_hours", ""), "phone": tags.get("phone", ""),
            "website": tags.get("website", ""), "cuisine": tags.get("cuisine", ""),
            "type": tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("leisure") or tags.get("railway") or "",
        })
    seen, deduped = set(), []
    for marker in sorted(markers, key=lambda item: item["distance_km"]):
        key = (marker["name"].casefold(), round(marker["lat"], 4), round(marker["lon"], 4))
        if key not in seen:
            seen.add(key)
            deduped.append(marker)
    return _queue_action("set_markers", query={"category": category_key, "radius_km": radius, "center": {"lat": lat, "lon": lon}}, markers=deduped[:result_limit], replace=True)


def clear_map_markers(category: str = "") -> str:
    """Clear all map markers or one category."""
    return _queue_action("clear_markers", category=(category or "").strip().lower())


def focus_map_marker(latitude: float, longitude: float, zoom: int = 17, name: str = "") -> str:
    """Center the HUD map on a known location."""
    return _queue_action("focus_marker", latitude=float(latitude), longitude=float(longitude), zoom=max(1, min(int(zoom), 20)), name=name or "")


MAP_HUD_TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "search_map_places", "description": "Search real nearby places and pin them on the open Jarvis map. Use MAP CONTEXT coordinates when available.", "parameters": {"type": "object", "properties": {"category": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}, "radius_km": {"type": "number"}, "limit": {"type": "integer"}}, "required": ["category", "latitude", "longitude"]}}},
    {"type": "function", "function": {"name": "clear_map_markers", "description": "Remove pins from the Jarvis map.", "parameters": {"type": "object", "properties": {"category": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "focus_map_marker", "description": "Focus the Jarvis map on a known location.", "parameters": {"type": "object", "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}, "zoom": {"type": "integer"}, "name": {"type": "string"}}, "required": ["latitude", "longitude"]}}},
]
MAP_HUD_TOOL_FUNCTIONS = {"search_map_places": search_map_places, "clear_map_markers": clear_map_markers, "focus_map_marker": focus_map_marker}
MAP_HUD_RISKY_TOOLS = set()
