"""
Google Maps integration for Jarvis.

This uses Google Maps URLs rather than the Google Maps API.
No Google API key is required.

OpenRouteService remains responsible for route calculations.
GeoLite2 / Windows Location Services remain responsible for
Jarvis's location.
"""

import webbrowser
from urllib.parse import urlencode


GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/"
GOOGLE_MAPS_DIRECTIONS_URL = "https://www.google.com/maps/dir/"


def _open_url(url: str) -> str:
    """Open a URL in the user's default browser."""
    try:
        opened = webbrowser.open(url)

        if not opened:
            return f"Could not open the browser. URL: {url}"

        return url

    except Exception as e:
        return f"Could not open Google Maps: {e}"


def open_google_maps(
    destination: str,
    travel_mode: str = "",
) -> str:
    """
    Open Google Maps directions to a destination.

    If travel_mode is omitted, Google Maps chooses the most relevant
    available mode.

    Supported modes:
        driving
        walking
        bicycling
        two-wheeler
        transit
    """

    if not destination or not destination.strip():
        return "A destination is required."

    destination = destination.strip()

    params = {
        "api": "1",
        "destination": destination,
    }

    if travel_mode:
        travel_mode = travel_mode.strip().lower()

        allowed_modes = {
            "driving",
            "walking",
            "bicycling",
            "two-wheeler",
            "transit",
        }

        if travel_mode not in allowed_modes:
            return (
                f"Unsupported travel mode '{travel_mode}'. "
                f"Use one of: {', '.join(sorted(allowed_modes))}."
            )

        params["travelmode"] = travel_mode

    url = GOOGLE_MAPS_DIRECTIONS_URL + "?" + urlencode(params)

    result = _open_url(url)

    if result.startswith("http"):
        mode_text = f" using {travel_mode}" if travel_mode else ""
        return f"Opened Google Maps directions to {destination}{mode_text}."

    return result


def navigate_google_maps(
    destination: str,
    travel_mode: str = "",
) -> str:
    """
    Open Google Maps navigation to a destination.

    Google Maps will use the device's current location when no origin
    is supplied.
    """

    if not destination or not destination.strip():
        return "A destination is required."

    destination = destination.strip()

    params = {
        "api": "1",
        "destination": destination,
        "dir_action": "navigate",
    }

    if travel_mode:
        travel_mode = travel_mode.strip().lower()

        allowed_modes = {
            "driving",
            "walking",
            "bicycling",
            "two-wheeler",
            "transit",
        }

        if travel_mode not in allowed_modes:
            return (
                f"Unsupported travel mode '{travel_mode}'. "
                f"Use one of: {', '.join(sorted(allowed_modes))}."
            )

        params["travelmode"] = travel_mode

    url = GOOGLE_MAPS_DIRECTIONS_URL + "?" + urlencode(params)

    result = _open_url(url)

    if result.startswith("http"):
        mode_text = f" using {travel_mode}" if travel_mode else ""
        return f"Opened Google Maps navigation to {destination}{mode_text}."

    return result


def search_google_maps(query: str) -> str:
    """
    Open a Google Maps search for a place or category.
    """

    if not query or not query.strip():
        return "A search query is required."

    query = query.strip()

    params = {
        "api": "1",
        "query": query,
    }

    url = GOOGLE_MAPS_SEARCH_URL + "?" + urlencode(params)

    result = _open_url(url)

    if result.startswith("http"):
        return f"Opened Google Maps search for {query}."

    return result


MAPS_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_google_maps",
            "description": (
                "Open Google Maps directions to a destination. "
                "Use this when the user asks to open directions, "
                "show directions, or view a route in Google Maps. "
                "This does not calculate the route itself; use "
                "get_route when the user needs distance or travel time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": (
                            "The destination place name or address, "
                            "for example 'India Gate, New Delhi'."
                        ),
                    },
                    "travel_mode": {
                        "type": "string",
                        "description": (
                            "Optional travel mode: driving, walking, "
                            "bicycling, two-wheeler, or transit."
                        ),
                    },
                },
                "required": ["destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_google_maps",
            "description": (
                "Open Google Maps navigation to a destination. "
                "Use this when the user explicitly says navigate, "
                "start navigation, take me to, or navigate me to. "
                "Google Maps uses the device's current location when "
                "the origin is omitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": (
                            "The destination place name or address."
                        ),
                    },
                    "travel_mode": {
                        "type": "string",
                        "description": (
                            "Optional travel mode: driving, walking, "
                            "bicycling, two-wheeler, or transit."
                        ),
                    },
                },
                "required": ["destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_google_maps",
            "description": (
                "Open a Google Maps search for a place or category. "
                "Use this when the user explicitly asks to search "
                "Google Maps for something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The place or search query, for example "
                            "'cafes near me' or 'India Gate'."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
]


MAPS_TOOL_FUNCTIONS = {
    "open_google_maps": open_google_maps,
    "navigate_google_maps": navigate_google_maps,
    "search_google_maps": search_google_maps,
}


# Opening a browser is not treated as a dangerous/destructive action.
MAPS_RISKY_TOOLS = set()