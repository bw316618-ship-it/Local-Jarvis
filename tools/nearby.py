"""
Nearby point-of-interest search for Jarvis using OpenStreetMap Overpass.

The search origin is always tools.location.get_coordinates(), so nearby
results are centred on the computer's current OS-provided location.

Read-only.
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
DEFAULT_RADIUS_KM = 5.0
MAX_RESULTS = 8

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

    # Attraction aliases.
    "attraction": [
        ("tourism", "attraction"),
        ("tourism", "museum"),
        ("tourism", "gallery"),
        ("tourism", "zoo"),
        ("tourism", "theme_park"),
        ("historic", "monument"),
        ("historic", "memorial"),
        ("historic", "castle"),
        ("historic", "archaeological_site"),
        ("leisure", "park"),
    ],
    "attractions": [
        ("tourism", "attraction"),
        ("tourism", "museum"),
        ("tourism", "gallery"),
        ("tourism", "zoo"),
        ("tourism", "theme_park"),
        ("historic", "monument"),
        ("historic", "memorial"),
        ("historic", "castle"),
        ("historic", "archaeological_site"),
        ("leisure", "park"),
    ],
    "tourist attraction": [
        ("tourism", "attraction"),
        ("tourism", "museum"),
        ("tourism", "gallery"),
        ("tourism", "zoo"),
        ("tourism", "theme_park"),
        ("historic", "monument"),
        ("historic", "memorial"),
        ("historic", "castle"),
        ("historic", "archaeological_site"),
        ("leisure", "park"),
    ],
    "tourist attractions": [
        ("tourism", "attraction"),
        ("tourism", "museum"),
        ("tourism", "gallery"),
        ("tourism", "zoo"),
        ("tourism", "theme_park"),
        ("historic", "monument"),
        ("historic", "memorial"),
        ("historic", "castle"),
        ("historic", "archaeological_site"),
        ("leisure", "park"),
    ],
}


def _haversine_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def _build_query(lat, lon, radius_m, tag_filters, free_text):
    clauses = []
    if tag_filters:
        for key, value in tag_filters:
            clauses.append(
                f'node["{key}"="{value}"](around:{radius_m},{lat},{lon});'
            )
            clauses.append(
                f'way["{key}"="{value}"](around:{radius_m},{lat},{lon});'
            )
            clauses.append(
                f'relation["{key}"="{value}"](around:{radius_m},{lat},{lon});'
            )
    else:
        escaped = free_text.replace("\\", "\\\\").replace('"', '\\"')
        clauses.append(
            f'node["name"~"{escaped}",i](around:{radius_m},{lat},{lon});'
        )
        clauses.append(
            f'way["name"~"{escaped}",i](around:{radius_m},{lat},{lon});'
        )

    return (
        f"[out:json][timeout:{REQUEST_TIMEOUT_SECONDS}];\n"
        "(\n  " + "\n  ".join(clauses) + "\n);\n"
        "out center;"
    )


def find_nearby_place(category, radius_km=DEFAULT_RADIUS_KM):
    """Find nearby places matching a category, sorted by distance."""
    category_key = (category or "").strip().lower()
    if not category_key:
        return "A category or place type is required."

    try:
        radius_km = max(0.1, min(float(radius_km), 25.0))
    except (TypeError, ValueError):
        radius_km = DEFAULT_RADIUS_KM

    try:
        here = get_coordinates()
    except RuntimeError as exc:
        return f"Could not determine current location:\n{exc}"

    tag_filters = CATEGORY_TAGS.get(category_key)
    query = _build_query(
        here["lat"],
        here["lon"],
        int(radius_km * 1000),
        tag_filters,
        category_key,
    )

    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=OVERPASS_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"Nearby-place search failed: {exc}"
    except ValueError:
        return "Nearby-place search failed: invalid JSON from Overpass."

    results = []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue

        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lon = element.get("lon") or (element.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        results.append(
            {
                "name": name,
                "lat": float(lat),
                "lon": float(lon),
                "distance_km": _haversine_km(
                    here["lat"], here["lon"], float(lat), float(lon)
                ),
                "type": next(
                    (
                        value
                        for key, value in tags.items()
                        if key in {"tourism", "historic", "leisure", "amenity", "railway"}
                    ),
                    None,
                ),
            }
        )

    if not results:
        return (
            f"No '{category}' found within {radius_km:.1f} km "
            "of the current location."
        )

    seen = set()
    deduped = []
    for result in sorted(results, key=lambda item: item["distance_km"]):
        key = (
            result["name"].casefold(),
            round(result["lat"], 4),
            round(result["lon"], 4),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)

    lines = []
    for result in deduped[:MAX_RESULTS]:
        distance = result["distance_km"]
        distance_text = (
            f"{distance * 1000:.0f} m" if distance < 1 else f"{distance:.2f} km"
        )
        kind = f" [{result['type']}]" if result["type"] else ""
        lines.append(f"- {result['name']}{kind} — {distance_text} away")

    return (
        f"Nearby '{category}' results from "
        f"{here['lat']:.5f}, {here['lon']:.5f}:\n"
        + "\n".join(lines)
    )


NEARBY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_nearby_place",
            "description": (
                "MANDATORY TOOL for nearby-location requests. Use this whenever "
                "the user asks for nearby, nearest, closest, near-me, or what is "
                "around them. Supports cafes, restaurants, pharmacies, metro "
                "stations, parks, tourist attractions, museums, monuments and "
                "other OpenStreetMap categories. Uses the computer's current "
                "location automatically and returns real nearby places."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Place type, e.g. 'cafe', 'restaurant', "
                            "'metro station', or 'tourist attractions'."
                        ),
                    },
                    "radius_km": {
                        "type": "number",
                        "description": "Search radius in kilometers; defaults to 5 and is capped at 25.",
                    },
                },
                "required": ["category"],
            },
        },
    }
]

NEARBY_TOOL_FUNCTIONS = {"find_nearby_place": find_nearby_place}
NEARBY_RISKY_TOOLS = set()
