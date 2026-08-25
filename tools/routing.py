"""
Route/directions for Jarvis: OpenRouteService for walking/cycling/driving
directions (free, needs an API key), the public OSRM demo server as a
keyless driving-only fallback, and Nominatim (OpenStreetMap's free
geocoding service) to resolve a destination given by name rather than
coordinates.

Complements tools/nearby.py's find_nearby_place -- a typical flow is
"find the nearest X" (returns a name + coordinates) then "route me
there" (this tool) -- but get_route also geocodes a plain destination
name on its own, so it doesn't strictly require a prior nearby-place
search.

This is the public-API approach chosen over a self-hosted OSRM/Valhalla
instance -- see the project roadmap. OpenRouteService's free tier is
generous for personal use but rate-limited; the OSRM demo server is
explicitly not meant for heavy/production use and only reliably serves
driving directions (no walking/cycling profile). If either becomes a
bottleneck, self-hosting is the next step, not a different public API.

Get a free OpenRouteService API key at
https://openrouteservice.org/dev/#/signup and set "ors_api_key" in
jarvis_config.json -- without it, get_route still works for driving
directions via OSRM, just not walking/cycling.

Read-only (only computes/returns a route, never changes anything), so
it isn't registered as risky.
"""

import requests

from config import CONFIG
from tools.location import get_coordinates
from tools.net import request_with_retry

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ORS_URL = "https://api.openrouteservice.org/v2/directions"
OSRM_DEMO_URL = "https://router.project-osrm.org/route/v1/driving"

REQUEST_TIMEOUT_SECONDS = 15

# What a person would say -> OpenRouteService's own profile identifier.
ORS_PROFILES = {
    "walking": "foot-walking",
    "foot": "foot-walking",
    "cycling": "cycling-regular",
    "bike": "cycling-regular",
    "driving": "driving-car",
    "car": "driving-car",
}

# Nominatim's usage policy requires a descriptive User-Agent identifying
# the application -- this is not optional, requests without one get
# blocked rather than just discouraged.
NOMINATIM_HEADERS = {"User-Agent": "Local-Jarvis/1.0 (personal offline assistant)"}


def _geocode(place_name: str) -> tuple:
    try:
        response = request_with_retry(
            "GET",
            NOMINATIM_URL,
            params={"q": place_name, "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        results = response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Could not look up '{place_name}': {e}") from e
    except ValueError:
        raise RuntimeError(f"Could not look up '{place_name}': unexpected response.")

    if not results:
        raise RuntimeError(f"No location found matching '{place_name}'.")

    return float(results[0]["lat"]), float(results[0]["lon"])


def _route_via_ors(profile: str, origin: tuple, destination: tuple) -> str:
    api_key = CONFIG.get("ors_api_key")
    if not api_key:
        raise RuntimeError("no OpenRouteService API key configured (set 'ors_api_key' in jarvis_config.json)")

    ors_profile = ORS_PROFILES.get(profile, "foot-walking")
    url = f"{ORS_URL}/{ors_profile}"
    # ORS wants [lon, lat] pairs, the opposite order from how this tool
    # otherwise talks about coordinates -- kept local to this function so
    # the mixup can't leak into the rest of the module.
    body = {"coordinates": [[origin[1], origin[0]], [destination[1], destination[0]]]}
    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    try:
        response = request_with_retry(
            "POST", url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        data = response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"OpenRouteService request failed: {e}") from e

    try:
        summary = data["routes"][0]["summary"]
        distance_km = summary["distance"] / 1000
        duration_min = summary["duration"] / 60
    except (KeyError, IndexError) as e:
        raise RuntimeError("OpenRouteService returned an unexpected response.") from e

    return f"Route ({profile}, via OpenRouteService): {distance_km:.2f} km, about {duration_min:.0f} minutes."


def _route_via_osrm(profile: str, origin: tuple, destination: tuple) -> str:
    if profile not in ("driving", "car"):
        raise RuntimeError(
            "the public OSRM demo server only reliably serves driving directions "
            "(configure 'ors_api_key' for walking/cycling)"
        )

    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    url = f"{OSRM_DEMO_URL}/{coords}"

    try:
        response = request_with_retry(
            "GET", url, params={"overview": "false"}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        data = response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"OSRM request failed: {e}") from e

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM could not find a route ({data.get('message', data.get('code'))}).")

    route = data["routes"][0]
    distance_km = route["distance"] / 1000
    duration_min = route["duration"] / 60
    return f"Route (driving, via OSRM): {distance_km:.2f} km, about {duration_min:.0f} minutes."


def get_route(
    destination_name: str = "",
    destination_lat: float = None,
    destination_lon: float = None,
    origin_lat: float = None,
    origin_lon: float = None,
    profile: str = "walking",
) -> str:
    """Get the distance and estimated time for a route to a destination,
    from the current location by default. Destination can be a place
    name (geocoded automatically) or explicit coordinates."""
    profile = (profile or "walking").strip().lower()

    if origin_lat is not None and origin_lon is not None:
        origin = (origin_lat, origin_lon)
    else:
        try:
            here = get_coordinates()
        except RuntimeError as e:
            return f"Could not determine the starting location:\n{e}"
        origin = (here["lat"], here["lon"])

    if destination_lat is not None and destination_lon is not None:
        destination = (destination_lat, destination_lon)
    elif destination_name.strip():
        try:
            destination = _geocode(destination_name.strip())
        except RuntimeError as e:
            return str(e)
    else:
        return "A destination is required -- either a place name or explicit coordinates."

    try:
        return _route_via_ors(profile, origin, destination)
    except RuntimeError as ors_error:
        try:
            return _route_via_osrm(profile, origin, destination)
        except RuntimeError as osrm_error:
            return f"Could not get a route:\n- OpenRouteService: {ors_error}\n- OSRM: {osrm_error}"


ROUTING_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_route",
            "description": (
                "Get the distance and estimated travel time to a destination, "
                "from the current location by default. Destination can be a "
                "place name (e.g. 'Eiffel Tower') or explicit latitude/longitude "
                "-- use find_nearby_place first to get coordinates for 'the "
                "nearest X', then pass those coordinates here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination_name": {
                        "type": "string",
                        "description": "Destination place name, geocoded automatically. Omit if giving explicit coordinates.",
                    },
                    "destination_lat": {
                        "type": "number",
                        "description": "Destination latitude, if known (e.g. from find_nearby_place).",
                    },
                    "destination_lon": {
                        "type": "number",
                        "description": "Destination longitude, if known (e.g. from find_nearby_place).",
                    },
                    "origin_lat": {
                        "type": "number",
                        "description": "Optional starting latitude. Defaults to the current location.",
                    },
                    "origin_lon": {
                        "type": "number",
                        "description": "Optional starting longitude. Defaults to the current location.",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["walking", "cycling", "driving"],
                        "description": "Mode of travel. Defaults to walking. Walking/cycling need an OpenRouteService API key configured.",
                    },
                },
                "required": [],
            },
        },
    },
]

ROUTING_TOOL_FUNCTIONS = {"get_route": get_route}

# Read-only -- only computes/returns a route, never changes anything.
ROUTING_RISKY_TOOLS = set()
