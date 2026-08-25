"""
Nearby point-of-interest search for Jarvis using OpenStreetMap Overpass.

Nearby searches also publish their results to the HUD map so that a request
such as "mark nearby cafes" both returns the places to Jarvis and visually
pins them on the map.

find_nearby_place is the ONLY Overpass-search tool exposed to the model.
tools/map_hud.py used to have a second, near-identical search_map_places
tool (its own CATEGORY_TAGS, its own query builder, its own haversine
distance) that only pinned the map and returned no summary text -- that
duplication made it ambiguous which tool the model would pick for a
"find X near me" request, and picking the map_hud one meant the user got
no readable answer. That tool has been removed; map_hud.py now only
owns the map-only actions (clear/focus) that this module doesn't cover.

Read-only.
"""

import math

import requests

from tools.location import get_coordinates
from tools.map_hud import _queue_action
from tools.net import request_with_retry


OVERPASS_URL = "https://overpass-api.de/api/interpreter"

REQUEST_TIMEOUT_SECONDS = 20

OVERPASS_HEADERS = {
    "User-Agent": "Local-Jarvis/1.0 (personal local-first AI assistant)",
    "Accept": "application/json",
}

DEFAULT_RADIUS_KM = 5.0
MAX_RESULTS = 30
MAX_RADIUS_KM = 25.0


CATEGORY_TAGS = {
    "metro station": [
        ("railway", "station"),
        ("station", "subway"),
        ("railway", "subway_entrance"),
    ],

    "subway station": [
        ("railway", "station"),
        ("station", "subway"),
        ("railway", "subway_entrance"),
    ],

    "train station": [
        ("railway", "station"),
    ],

    "bus stop": [
        ("highway", "bus_stop"),
    ],

    "pharmacy": [
        ("amenity", "pharmacy"),
    ],

    "hospital": [
        ("amenity", "hospital"),
    ],

    "gas station": [
        ("amenity", "fuel"),
    ],

    "petrol station": [
        ("amenity", "fuel"),
    ],

    "atm": [
        ("amenity", "atm"),
    ],

    "bank": [
        ("amenity", "bank"),
    ],

    "supermarket": [
        ("shop", "supermarket"),
    ],

    "grocery store": [
        ("shop", "supermarket"),
        ("shop", "convenience"),
    ],

    "restaurant": [
        ("amenity", "restaurant"),
    ],

    "cafe": [
        ("amenity", "cafe"),
    ],

    "cafes": [
        ("amenity", "cafe"),
    ],

    "coffee shop": [
        ("amenity", "cafe"),
    ],

    "coffee shops": [
        ("amenity", "cafe"),
    ],

    "parking": [
        ("amenity", "parking"),
    ],

    "hotel": [
        ("tourism", "hotel"),
    ],

    "post office": [
        ("amenity", "post_office"),
    ],

    "library": [
        ("amenity", "library"),
    ],

    "park": [
        ("leisure", "park"),
    ],

    "museum": [
        ("tourism", "museum"),
    ],

    "gallery": [
        ("tourism", "gallery"),
    ],

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

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(d_lambda / 2) ** 2
    )

    return 2 * earth_radius_km * math.asin(
        math.sqrt(a)
    )


def _build_query(
    lat,
    lon,
    radius_m,
    tag_filters,
    free_text,
):
    clauses = []

    if tag_filters:
        for key, value in tag_filters:
            clauses.append(
                f'node["{key}"="{value}"]'
                f'(around:{radius_m},{lat},{lon});'
            )

            clauses.append(
                f'way["{key}"="{value}"]'
                f'(around:{radius_m},{lat},{lon});'
            )

            clauses.append(
                f'relation["{key}"="{value}"]'
                f'(around:{radius_m},{lat},{lon});'
            )

    else:
        escaped = (
            free_text
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        clauses.append(
            f'node["name"~"{escaped}",i]'
            f'(around:{radius_m},{lat},{lon});'
        )

        clauses.append(
            f'way["name"~"{escaped}",i]'
            f'(around:{radius_m},{lat},{lon});'
        )

    return (
        f"[out:json][timeout:{REQUEST_TIMEOUT_SECONDS}];\n"
        "(\n  "
        + "\n  ".join(clauses)
        + "\n);\n"
        "out center;"
    )


def _build_marker(element, here, category):
    tags = element.get("tags") or {}

    name = tags.get("name")

    if not name:
        return None

    center = element.get("center") or {}

    lat = element.get("lat")

    if lat is None:
        lat = center.get("lat")

    lon = element.get("lon")

    if lon is None:
        lon = center.get("lon")

    if lat is None or lon is None:
        return None

    lat = float(lat)
    lon = float(lon)

    address_parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:city"),
        tags.get("addr:postcode"),
    ]

    address = ", ".join(
        part
        for part in address_parts
        if part
    )

    place_type = (
        tags.get("amenity")
        or tags.get("shop")
        or tags.get("tourism")
        or tags.get("historic")
        or tags.get("leisure")
        or tags.get("railway")
        or ""
    )

    return {
        "id": (
            f"{element.get('type', 'place')}-"
            f"{element.get('id', '0')}"
        ),

        "name": name,

        "lat": lat,
        "lon": lon,

        "distance_km": _haversine_km(
            here["lat"],
            here["lon"],
            lat,
            lon,
        ),

        "category": category,

        "type": place_type,

        "address": address,

        "opening_hours": tags.get(
            "opening_hours",
            "",
        ),

        "phone": (
            tags.get("phone")
            or tags.get("contact:phone")
            or ""
        ),

        "website": (
            tags.get("website")
            or tags.get("contact:website")
            or ""
        ),

        "cuisine": tags.get(
            "cuisine",
            "",
        ),
    }


def _deduplicate(results):
    seen = set()
    deduped = []

    for result in sorted(
        results,
        key=lambda item: item["distance_km"],
    ):
        key = (
            result["name"].casefold(),
            round(result["lat"], 4),
            round(result["lon"], 4),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(result)

    return deduped


def _format_distance(distance_km):
    if distance_km < 1:
        return f"{distance_km * 1000:.0f} m"

    return f"{distance_km:.2f} km"


def _publish_markers(
    category,
    radius_km,
    here,
    markers,
):
    """
    Send the same nearby results to the HUD map.

    This is the missing connection between the normal nearby tool
    and the graphical map.
    """

    _queue_action(
        "set_markers",

        query={
            "category": category,
            "radius_km": radius_km,
            "center": {
                "lat": here["lat"],
                "lon": here["lon"],
            },
        },

        markers=markers,

        replace=True,
    )


def find_nearby_place(
    category,
    radius_km=DEFAULT_RADIUS_KM,
):
    """
    Find nearby places matching a category.

    The result is both:
      1. returned to Jarvis as text
      2. published as map markers to the HUD
    """

    category_key = (
        (category or "")
        .strip()
        .lower()
    )

    if not category_key:
        return (
            "A category or place type "
            "is required."
        )

    try:
        radius_km = max(
            0.1,
            min(
                float(radius_km),
                MAX_RADIUS_KM,
            ),
        )

    except (TypeError, ValueError):
        radius_km = DEFAULT_RADIUS_KM

    try:
        here = get_coordinates()

    except RuntimeError as exc:
        return (
            "Could not determine current "
            f"location:\n{exc}"
        )

    tag_filters = CATEGORY_TAGS.get(
        category_key
    )

    query = _build_query(
        here["lat"],
        here["lon"],
        int(radius_km * 1000),
        tag_filters,
        category_key,
    )

    try:
        response = request_with_retry(
            "POST",
            OVERPASS_URL,
            data={
                "data": query,
            },
            headers=OVERPASS_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        data = response.json()

    except requests.RequestException as exc:
        return (
            "Nearby-place search failed: "
            f"{exc}"
        )

    except ValueError:
        return (
            "Nearby-place search failed: "
            "invalid JSON from Overpass."
        )

    results = []

    for element in data.get(
        "elements",
        [],
    ):
        marker = _build_marker(
            element,
            here,
            category_key,
        )

        if marker is not None:
            results.append(marker)

    results = _deduplicate(results)

    if not results:
        return (
            f"No '{category}' found within "
            f"{radius_km:.1f} km of the "
            "current location."
        )

    markers = results[:MAX_RESULTS]

    # ------------------------------------------------------------
    # THIS IS THE IMPORTANT PART.
    #
    # Previously find_nearby_place() stopped after producing text.
    # Now the same results are pushed into the HUD map queue.
    # ------------------------------------------------------------

    _publish_markers(
        category=category_key,
        radius_km=radius_km,
        here=here,
        markers=markers,
    )

    lines = []

    for result in markers:
        distance_text = _format_distance(
            result["distance_km"]
        )

        kind = (
            f" [{result['type']}]"
            if result["type"]
            else ""
        )

        lines.append(
            f"- {result['name']}"
            f"{kind} — "
            f"{distance_text} away"
        )

    return (
        f"Nearby '{category}' results from "
        f"{here['lat']:.5f}, "
        f"{here['lon']:.5f}:\n"
        + "\n".join(lines)
        + "\n\n"
        f"Displayed {len(markers)} result(s) "
        "on the Jarvis map."
    )


NEARBY_TOOL_SCHEMAS = [
    {
        "type": "function",

        "function": {
            "name": "find_nearby_place",

            "description": (
                "MANDATORY TOOL for nearby-location requests. "
                "Use this whenever the user asks for nearby, "
                "nearest, closest, near-me, or what is around "
                "them. Supports cafes, restaurants, pharmacies, "
                "metro stations, parks, tourist attractions, "
                "museums, monuments and other OpenStreetMap "
                "categories. Uses the computer's current "
                "location automatically and returns real "
                "nearby places. Results are also pinned on "
                "the HUD map, which opens automatically if "
                "it wasn't already."
            ),

            "parameters": {
                "type": "object",

                "properties": {
                    "category": {
                        "type": "string",

                        "description": (
                            "Place type, e.g. 'cafe', "
                            "'restaurant', 'metro station', "
                            "or 'tourist attractions'."
                        ),
                    },

                    "radius_km": {
                        "type": "number",

                        "description": (
                            "Search radius in kilometers; "
                            "defaults to 5 and is capped "
                            "at 25."
                        ),
                    },
                },

                "required": [
                    "category",
                ],
            },
        },
    }
]


NEARBY_TOOL_FUNCTIONS = {
    "find_nearby_place": find_nearby_place,
}


NEARBY_RISKY_TOOLS = set()
