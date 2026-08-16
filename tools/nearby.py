"""
Nearby point-of-interest search for Jarvis, via the Overpass API
(OpenStreetMap's live query interface) -- free, keyless, no signup.

Resolves the current location the same way tools/location.py's
get_location() does (OS-native first, local MaxMind DB fallback via
get_coordinates()), then searches OpenStreetMap's crowdsourced POI data
for real places near it, sorted by straight-line distance.

Category coverage is a curated mapping from common everyday terms
("metro station", "pharmacy") to the OSM tags that actually mark those
places -- OSM's tagging scheme is detailed and inconsistent enough that
a plain name search misses most transit/amenity data. Anything not in
the mapping falls back to a free-text name search instead of failing
outright.

This is the public-API approach chosen over a self-hosted Overpass
mirror -- see the project roadmap. The public Overpass instance is free
but shared/rate-limited; if that becomes a problem, self-hosting is the
next step, not a different public API.

Read-only (only searches, never changes anything), so it isn't
registered as risky.
"""

import math

import requests

from tools.location import get_coordinates

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REQUEST_TIMEOUT_SECONDS = 20

OVERPASS_HEADERS = {
    "User-Agent": "Local-Jarvis/1.0 (personal local-first AI assistant)",
    "Accept": "application/json",
}
DEFAULT_RADIUS_KM = 2.0
MAX_RESULTS = 5

# category name -> OSM (key, value) tag filters. A place matching ANY of
# the listed filters counts. Not exhaustive -- add more as you need them.
CATEGORY_TAGS = {
    "metro station": [("railway", "station"), ("station", "subway"), ("railway", "subway_entrance")],
    "subway station": [("railway", "station"), ("station", "subway"), ("railway", "subway_entrance")],
    "train station": [("railway", "station")],
    "bus stop": [("highway", "bus_stop")],
    "pharmacy": [("amenity", "pharmacy")],
    "hospital": [("amenity", "hospital")],
    "gas station": [("amenity", "fuel")],
    "petrol station": [("amenity", "fuel")],
    "atm": [("amenity", "atm")],
    "bank": [("amenity", "bank")],
    "supermarket": [("shop", "supermarket")],
    "grocery store": [("shop", "supermarket"), ("shop", "convenience")],
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "coffee shop": [("amenity", "cafe")],
    "parking": [("amenity", "parking")],
    "hotel": [("tourism", "hotel")],
    "post office": [("amenity", "post_office")],
    "library": [("amenity", "library")],
    "park": [("leisure", "park")],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def _build_query(lat: float, lon: float, radius_m: int, tag_filters, free_text: str) -> str:
    clauses = []
    if tag_filters:
        for key, value in tag_filters:
            clauses.append(f'node["{key}"="{value}"](around:{radius_m},{lat},{lon});')
            clauses.append(f'way["{key}"="{value}"](around:{radius_m},{lat},{lon});')
    else:
        escaped = free_text.replace('"', '\\"')
        clauses.append(f'node["name"~"{escaped}",i](around:{radius_m},{lat},{lon});')
        clauses.append(f'way["name"~"{escaped}",i](around:{radius_m},{lat},{lon});')

    body = "\n  ".join(clauses)
    return f"[out:json][timeout:{REQUEST_TIMEOUT_SECONDS}];\n(\n  {body}\n);\nout center;"


def find_nearby_place(category: str, radius_km: float = DEFAULT_RADIUS_KM) -> str:
    """Find the nearest places matching `category` (e.g. 'metro station',
    'pharmacy') to the current location, using OpenStreetMap data."""
    category_key = (category or "").strip().lower()
    if not category_key:
        return "A category or place type is required, e.g. 'metro station'."

    try:
        here = get_coordinates()
    except RuntimeError as e:
        return f"Could not determine current location:\n{e}"

    tag_filters = CATEGORY_TAGS.get(category_key)
    query = _build_query(here["lat"], here["lon"], int(radius_km * 1000), tag_filters, category_key)

    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=OVERPASS_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return f"Nearby-place search failed: {e}"
    except ValueError:
        return "Nearby-place search failed: the Overpass API returned an unexpected response."

    results = []
    for el in data.get("elements", []):
        name = (el.get("tags") or {}).get("name")
        if not name:
            continue
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        distance_km = _haversine_km(here["lat"], here["lon"], lat, lon)
        results.append({"name": name, "lat": lat, "lon": lon, "distance_km": distance_km})

    if not results:
        return f"No '{category}' found within {radius_km:.1f} km of the current location."

    # Overpass can return the same POI as both a node and a way if it's
    # tagged unusually -- de-dupe by name + rounded coordinates.
    seen = set()
    deduped = []
    for r in sorted(results, key=lambda r: r["distance_km"]):
        key = (r["name"], round(r["lat"], 4), round(r["lon"], 4))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    top = deduped[:MAX_RESULTS]
    lines = [
        f"- {r['name']} -- {r['distance_km'] * 1000:.0f} m away ({r['lat']:.5f}, {r['lon']:.5f})"
        for r in top
    ]
    return f"Nearest '{category}' results:\n" + "\n".join(lines)


NEARBY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_nearby_place",
            "description": (
                "MANDATORY TOOL for nearby-location requests. "
                "Use this tool whenever the user asks for nearby, nearest, closest, "
                "or near-me places. Examples include 'nearby cafes', "
                "'nearest metro station', 'closest pharmacy', 'restaurants near me', "
                "'what is around me', and 'find coffee shops nearby'. "
                "This tool uses the computer's current location and live "
                "OpenStreetMap data. It returns real nearby places and their "
                "coordinates. Do NOT claim that you lack live mapping data or "
                "real-time location access; this tool provides that capability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "The type of place to search for, e.g. 'metro station'.",
                    },
                    "radius_km": {
                        "type": "number",
                        "description": "Search radius in kilometers. Defaults to 2.",
                    },
                },
                "required": ["category"],
            },
        },
    },
]

NEARBY_TOOL_FUNCTIONS = {"find_nearby_place": find_nearby_place}

# Read-only -- only searches, never changes anything.
NEARBY_RISKY_TOOLS = set()
