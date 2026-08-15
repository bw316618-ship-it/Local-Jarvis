"""
IP-based geolocation for Jarvis.

There's no GPS on a typical desktop/laptop, so this estimates location
from the machine's public IP address via a free, keyless API
(ip-api.com). That means accuracy is roughly city-level, not exact
coordinates -- and unlike every other tool in this codebase, it
necessarily sends the machine's public IP to a third-party service to do
its job. If that's not something you want Jarvis doing, don't wire this
tool in.

Read-only (never changes anything), so it isn't registered as risky.
"""

import requests

IP_API_URL = "http://ip-api.com/json/"
REQUEST_TIMEOUT_SECONDS = 5


def get_location() -> str:
    """Estimate the machine's current location from its public IP address."""
    try:
        response = requests.get(IP_API_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return f"Could not determine location: {e}"
    except ValueError:
        return "Could not determine location: the geolocation service returned an unexpected response."

    if data.get("status") != "success":
        return f"Could not determine location: {data.get('message', 'unknown error')}"

    city = data.get("city") or "unknown city"
    region = data.get("regionName") or ""
    country = data.get("country") or "unknown country"
    lat = data.get("lat")
    lon = data.get("lon")
    isp = data.get("isp") or "unknown ISP"

    place = f"{city}, {region}, {country}" if region else f"{city}, {country}"
    coords = f" (approx. {lat}, {lon})" if lat is not None and lon is not None else ""
    return (
        f"Approximate location: {place}{coords}. This is IP-based (via {isp}), "
        "so it's city-level accuracy at best, not exact."
    )


LOCATION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": (
                "Estimate the current location of this machine from its public IP "
                "address. This is city-level accuracy at best (no GPS on a desktop/"
                "laptop) -- use it for 'roughly where am I' questions, not precise "
                "navigation."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

LOCATION_TOOL_FUNCTIONS = {"get_location": get_location}

# Read-only -- looking up an IP's location never changes anything.
LOCATION_RISKY_TOOLS = set()
