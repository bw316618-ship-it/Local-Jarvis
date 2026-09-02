"""
Nearby point-of-interest search for Jarvis using OpenStreetMap Overpass.

Nearby searches also publish their results to the HUD map.

The Overpass client uses multiple public instances and fails over between
them when one is rate-limited, overloaded, or temporarily unavailable.
"""

import math
import threading
import time

import requests

from tools.location import get_coordinates
from tools.map_hud import _queue_action


# Public Overpass instances. Private.coffee is the preferred endpoint;
# the main FOSSGISS instance is kept as a last-resort fallback because
# it is currently the endpoint most likely to return HTTP 429.
OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)

# Keep the server-side query timeout and HTTP timeout aligned. The old
# implementation spent 20 seconds on each endpoint and could therefore
# block for more than a minute when public Overpass instances were busy.
REQUEST_TIMEOUT_SECONDS = 15
NETWORK_RETRIES_PER_ENDPOINT = 0
OVERPASS_COOLDOWN_SECONDS = 30.0
OVERPASS_MIN_INTERVAL_SECONDS = 1.0

OVERPASS_HEADERS = {
    "User-Agent": "Local-Jarvis/1.0 (personal local-first AI assistant)",
    "Accept": "application/json",
}

DEFAULT_RADIUS_KM = 5.0
MAX_RESULTS = 30
MAX_RADIUS_KM = 25.0

_endpoint_lock = threading.Lock()
_endpoint_cooldowns = {}
_last_request_at = 0.0
_preferred_endpoint_index = 0


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
        math.sqrt(max(0.0, min(1.0, a)))
    )


def _build_query(
    lat,
    lon,
    radius_m,
    tag_filters,
    free_text,
):
    """
    Build a deliberately small Overpass query.

    The old version emitted three separate clauses (node, way, relation)
    for every tag. For a simple cafe search that was already three
    searches; attraction searches expanded into dozens of independent
    searches. `nwr` expresses the same request as one selector and is
    substantially cheaper for public Overpass instances.
    """
    clauses = []

    if tag_filters:
        for key, value in tag_filters:
            clauses.append(
                f'nwr["{key}"="{value}"]'
                f'(around:{radius_m},{lat},{lon});'
            )
    else:
        escaped = (
            free_text
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        clauses.append(
            f'nwr["name"~"{escaped}",i]'
            f'(around:{radius_m},{lat},{lon});'
        )

    return (
        f"[out:json][timeout:{REQUEST_TIMEOUT_SECONDS}];\n"
        "(\n  "
        + "\n  ".join(clauses)
        + "\n);\n"
        "out center;"
    )


def _retry_after_seconds(response):
    value = response.headers.get("Retry-After")

    if not value:
        return 0.0

    try:
        return max(0.0, min(float(value), 30.0))
    except (TypeError, ValueError):
        return 0.0


def _mark_endpoint_cooldown(index, seconds=OVERPASS_COOLDOWN_SECONDS):
    with _endpoint_lock:
        _endpoint_cooldowns[index] = time.monotonic() + seconds


def _wait_for_global_interval():
    global _last_request_at

    with _endpoint_lock:
        now = time.monotonic()
        wait = (
            OVERPASS_MIN_INTERVAL_SECONDS
            - (now - _last_request_at)
        )

        if wait > 0:
            time.sleep(wait)

        _last_request_at = time.monotonic()


def _endpoint_order():
    with _endpoint_lock:
        preferred = _preferred_endpoint_index

    return [
        (preferred + offset) % len(OVERPASS_URLS)
        for offset in range(len(OVERPASS_URLS))
    ]


def _request_overpass(query):
    """
    Query Overpass with endpoint failover.

    429 is NOT retried against the same server. The endpoint is cooled
    down and the next public instance is tried instead. Network failures
    and 5xx responses also move to the next endpoint after one retry.
    """

    global _preferred_endpoint_index

    errors = []

    for index in _endpoint_order():
        url = OVERPASS_URLS[index]

        with _endpoint_lock:
            cooldown_until = _endpoint_cooldowns.get(index, 0.0)

        if cooldown_until > time.monotonic():
            remaining = cooldown_until - time.monotonic()
            errors.append(
                f"{url}: cooling down ({remaining:.0f}s)"
            )
            continue

        endpoint_failed = False

        for attempt in range(NETWORK_RETRIES_PER_ENDPOINT + 1):
            try:
                _wait_for_global_interval()

                response = requests.post(
                    url,
                    data={"data": query},
                    headers=OVERPASS_HEADERS,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )

                status = response.status_code

                if status == 429:
                    retry_after = _retry_after_seconds(response)
                    _mark_endpoint_cooldown(
                        index,
                        max(
                            OVERPASS_COOLDOWN_SECONDS,
                            retry_after,
                        ),
                    )

                    errors.append(
                        f"{url}: HTTP 429 rate limited"
                    )
                    endpoint_failed = True
                    break

                if status in {500, 502, 503, 504}:
                    _mark_endpoint_cooldown(index, 30.0)
                    errors.append(
                        f"{url}: HTTP {status}"
                    )
                    endpoint_failed = True
                    break

                response.raise_for_status()

                data = response.json()

                if not isinstance(data, dict):
                    raise ValueError(
                        "Overpass returned a non-object JSON response."
                    )

                with _endpoint_lock:
                    _preferred_endpoint_index = index

                return data

            except requests.RequestException as exc:
                errors.append(
                    f"{url}: {exc}"
                )

                if attempt < NETWORK_RETRIES_PER_ENDPOINT:
                    time.sleep(0.5 * (attempt + 1))
                    continue

                _mark_endpoint_cooldown(index, 10.0)
                endpoint_failed = True
                break

            except ValueError as exc:
                errors.append(
                    f"{url}: {exc}"
                )
                endpoint_failed = True
                break

        if not endpoint_failed:
            break

    raise RuntimeError(
        "All Overpass endpoints failed. "
        + " | ".join(errors)
    )


def _reduced_query(lat, lon, radius_m, tag_filters, free_text):
    """
    Second-pass query used after a timeout.

    It keeps only nodes and ways. Relations are uncommon for the POIs
    Jarvis displays and are disproportionately expensive on overloaded
    public instances.
    """
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
        part for part in address_parts if part
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
        "opening_hours": tags.get("opening_hours", ""),
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
        "cuisine": tags.get("cuisine", ""),
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

    Results are both returned as text and published to the HUD map.
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

    tag_filters = CATEGORY_TAGS.get(category_key)

    query = _build_query(
        here["lat"],
        here["lon"],
        int(radius_km * 1000),
        tag_filters,
        category_key,
    )

    try:
        data = _request_overpass(query)

    except RuntimeError as first_error:
        # A busy Overpass server can still time out on a broad query.
        # Retry once with a cheaper nodes/ways-only query and a smaller
        # radius before reporting failure.
        reduced_radius_km = min(radius_km, 2.0)

        if reduced_radius_km < radius_km:
            reduced_query = _reduced_query(
                here["lat"],
                here["lon"],
                int(reduced_radius_km * 1000),
                tag_filters,
                category_key,
            )

            try:
                data = _request_overpass(reduced_query)
            except RuntimeError as second_error:
                return (
                    "Nearby-place search failed. "
                    f"Primary search: {first_error}. "
                    f"Reduced search: {second_error}"
                )
        else:
            return (
                "Nearby-place search failed: "
                f"{first_error}"
            )

    results = []

    for element in data.get("elements", []):
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
