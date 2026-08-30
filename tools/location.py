"""
Location for Jarvis -- OS-native location services first, a local
offline IP-geolocation database as a fallback, no live third-party
geolocation API called directly by this code.

There's no GPS chip on a typical desktop (laptops sometimes have one),
so "where is this machine" ultimately comes from one of two places:

  1. The operating system's own location service (Windows Geolocator,
     macOS CoreLocation) -- tried first on those platforms. This is the
     same mechanism behind "Chrome wants to use your location" prompts:
     the OS handles the actual positioning (GPS if present, otherwise
     its own WiFi/network-based estimate) and gates it behind its own
     permission prompt, so Jarvis itself never makes a raw HTTP call to
     resolve a location. No equivalent exists on Linux.

  2. A local, offline MaxMind GeoLite2-City database (a downloadable
     .mmdb file) as the fallback everywhere else -- once it's on disk,
     resolving an IP to an approximate location is a pure local lookup,
     no per-query network call. It still needs to know the machine's
     *public* IP first, since a machine behind a router doesn't
     inherently know that -- this is the one unavoidable network call
     in the whole flow, and it goes to a plain "what's my IP" echo
     service (ipify) that only ever sees and returns your IP, not your
     location; the location itself is computed entirely offline against
     the local database afterward.

The GeoLite2-City.mmdb file isn't bundled (MaxMind's license terms don't
allow redistributing it) -- download it yourself:
  1. Create a free MaxMind account: https://www.maxmind.com/en/geolite2/signup
  2. Under "Manage License Keys", generate a license key
  3. Download "GeoLite2 City" in MMDB format from
     https://www.maxmind.com/en/accounts/current/geoip/downloads
  4. Place the extracted GeoLite2-City.mmdb file in a geoip/ folder at
     the project root (same pattern as voices/ for Piper voice models)

If neither an OS-native service nor the local database is available,
get_location() says so plainly rather than silently falling back to a
live third-party API.

get_coordinates() is the raw-data counterpart get_location() is built
on, exported for other tools to chain off of (tools/nearby.py's
find_nearby_place, tools/routing.py's get_route) without re-parsing a
formatted sentence back into numbers. It's not itself registered as an
LLM tool -- get_location() is the model-facing entry point for "where
am I", and the two other tools already resolve the current location
internally via get_coordinates() when no explicit origin is given.

Read-only (never changes anything), so get_location isn't registered as
risky.
"""

import platform
from pathlib import Path

import geoip2.database
import geoip2.errors
import requests

from tools.net import request_with_retry

BASE_DIR = Path(__file__).resolve().parent.parent
GEOIP_DB_PATH = BASE_DIR / "geoip" / "GeoLite2-City.mmdb"

IP_ECHO_URL = "https://api.ipify.org"  # returns plain-text IP only, no location computed server-side
REQUEST_TIMEOUT_SECONDS = 5

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent": "Local-Jarvis/1.0 (personal local-first AI assistant)"
}


def _reverse_geocode(lat: float, lon: float) -> dict:
    try:
        response = request_with_retry(
            "GET",
            NOMINATIM_REVERSE_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
            },
            headers=NOMINATIM_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        return {
            "city": None,
            "region": None,
            "country": None,
        }
    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("village")
    )
    region = (
        address.get("state")
        or address.get("state_district")
        or address.get("county")
    )
    country = address.get("country")
    return {
        "city": city,
        "region": region,
        "country": country,
    }


def reverse_geocode_place(lat: float, lon: float) -> dict:
    """Reverse-geocode a single map coordinate into a marker-shaped dict
    for the HUD's "click anywhere on the map" feature.

    Distinct from _reverse_geocode() above -- that one only extracts
    city/region/country for use in Jarvis's own "where are you" location
    context, and its return shape reflects that narrow purpose. This one
    is for a person clicking an arbitrary point on the HUD map and
    wanting to see what's there, so it returns the same marker shape
    ui/hud/static/map_agent.js's showDetails()/focusMarker() already
    render for Overpass-sourced markers (tools/nearby.py's
    _build_marker) -- name, address, type, lat, lon -- so the frontend
    needs no separate rendering path for a reverse-geocode result.

    Nominatim's reverse endpoint describes an address, not a business,
    so website/phone/opening_hours/cuisine are typically unavailable
    here even when they would be for the same spot via an Overpass POI
    search -- the marker shape includes those keys as None rather than
    omitting them, since the frontend already renders each field only
    if truthy.
    """
    try:
        response = request_with_retry(
            "GET",
            NOMINATIM_REVERSE_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
            },
            headers=NOMINATIM_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"Could not identify this location: {exc}"}

    if not data or "error" in data:
        return {"error": "No address found for this location."}

    address = data.get("address", {})

    name = (
        data.get("name")
        or address.get("amenity")
        or address.get("shop")
        or address.get("building")
        or address.get("road")
        or data.get("display_name", "").split(",")[0]
        or "Selected location"
    )

    place_type = (
        data.get("type")
        or data.get("class")
        or ""
    ).replace("_", " ")

    return {
        "name": name,
        "address": data.get("display_name"),
        "type": place_type,
        "category": place_type,
        "website": None,
        "phone": None,
        "opening_hours": None,
        "cuisine": None,
        "distance_km": None,
        "lat": float(lat),
        "lon": float(lon),
    }


def _windows_coordinates() -> dict:
    """Run the WinRT Geolocation query (which is natively async) on its
    own dedicated thread with its own event loop, rather than calling
    asyncio.run() directly on the calling thread.

    get_coordinates() is called from plenty of places that already have
    an event loop running on the calling thread -- e.g. backend.py's
    WebSocket handler processes each tool call from inside its own
    asyncio loop. asyncio.run() refuses to start a second loop on a
    thread that already has one, which previously either raised or
    (depending on call path) got swallowed by the try/except in
    get_coordinates() and silently fell through to the GeoLite2 fallback
    -- so Windows users calling Jarvis via the backend/HUD always got
    GeoLite2-level accuracy even though Windows Location Services worked
    fine when tested standalone. Running the query on its own thread
    sidesteps that entirely: that thread has no pre-existing loop, so
    asyncio.run() there is always safe, regardless of what the caller's
    thread is doing.
    """
    try:
        import asyncio
        import threading

        from winsdk.windows.devices.geolocation import Geolocator, GeolocationAccessStatus
    except ImportError as e:
        raise RuntimeError(
            "Windows Location Services aren't available without the optional "
            "'winsdk' package. Run: pip install winsdk"
        ) from e

    # NOTE: winsdk wraps the WinRT Geolocation API 1:1, but this project's
    # dev sandbox has no Windows machine to run it against -- the property
    # names below (coordinate.point.position, civic_address.city, etc.)
    # match the documented WinRT surface, but if a Windows SDK update
    # changes the projection, this is the first place to check.
    async def _query():
        access_status = await Geolocator.request_access_async()
        if access_status != GeolocationAccessStatus.ALLOWED:
            raise RuntimeError(
                "Location access was denied. Enable it under Windows Settings > "
                "Privacy & security > Location for Python to use it, then try again."
            )
        geolocator = Geolocator()
        position = await geolocator.get_geoposition_async()
        coord = position.coordinate
        lat = coord.point.position.latitude
        lon = coord.point.position.longitude
        # Civic address belongs to Geoposition, not Geocoordinate.
        civic = position.civic_address
        city = civic.city if civic else None
        region = civic.state if civic else None
        country = civic.country if civic else None
        return city, region, country, lat, lon

    result = {}
    error = {}

    def worker():
        try:
            result["value"] = asyncio.run(_query())
        except Exception as e:
            error["value"] = e

    thread = threading.Thread(target=worker, name="windows-location")
    thread.start()
    thread.join()

    if "value" in error:
        raise RuntimeError(
            f"Windows Location Services failed: {error['value']}"
        ) from error["value"]
    if "value" not in result:
        raise RuntimeError("Windows Location Services returned no result.")

    city, region, country, lat, lon = result["value"]
    if not city and not region and not country:
        address = _reverse_geocode(lat, lon)
        city = address["city"]
        region = address["region"]
        country = address["country"]
    return {"lat": lat, "lon": lon, "city": city, "region": region, "country": country, "source": "Windows Location Services"}


def _macos_coordinates() -> dict:
    try:
        import time

        from CoreLocation import (
            CLLocationManager,
            kCLAuthorizationStatusAuthorizedAlways,
        )
    except ImportError as e:
        raise RuntimeError(
            "macOS Location Services aren't available without the optional "
            "'pyobjc-framework-CoreLocation' package. Run: "
            "pip install pyobjc-framework-CoreLocation"
        ) from e

    # CoreLocation is delegate/run-loop driven, not a simple blocking call --
    # this polls briefly rather than wiring up a full NSApplication event
    # loop, which is overkill for a one-shot CLI lookup. Also untested on
    # real hardware in this project's dev sandbox (Linux) -- verify the
    # authorization/permission flow on an actual Mac before relying on it,
    # since an unsigned/unbundled script may need Terminal (not "Jarvis")
    # granted access under System Settings > Privacy & Security > Location.
    manager = CLLocationManager.alloc().init()
    manager.startUpdatingLocation()

    location = None
    for _ in range(50):  # ~5 seconds
        location = manager.location()
        if location is not None:
            break
        time.sleep(0.1)
    manager.stopUpdatingLocation()

    if location is None:
        status = CLLocationManager.authorizationStatus()
        if status != kCLAuthorizationStatusAuthorizedAlways:
            raise RuntimeError(
                "Location access hasn't been granted. Enable it under System "
                "Settings > Privacy & Security > Location Services, then try again."
            )
        raise RuntimeError("Could not get a location fix from macOS Location Services.")

    coord = location.coordinate()
    return {"lat": coord.latitude, "lon": coord.longitude, "city": None, "region": None, "country": None, "source": "macOS Location Services"}


def _get_public_ip() -> str:
    try:
        response = request_with_retry("GET", IP_ECHO_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        ip = response.text.strip()
    except requests.RequestException as e:
        raise RuntimeError(f"Could not determine the public IP address: {e}") from e

    if not ip:
        raise RuntimeError("The IP-echo service returned an empty response.")
    return ip


def _maxmind_coordinates() -> dict:
    if not GEOIP_DB_PATH.exists():
        raise RuntimeError(
            f"No local GeoLite2 database found at '{GEOIP_DB_PATH}'. Download "
            "GeoLite2-City.mmdb from a free MaxMind account "
            "(https://www.maxmind.com/en/geolite2/signup) and place it there -- "
            "see the module docstring in tools/location.py for the full steps."
        )

    ip = _get_public_ip()

    try:
        with geoip2.database.Reader(str(GEOIP_DB_PATH)) as reader:
            record = reader.city(ip)
    except geoip2.errors.AddressNotFoundError as e:
        raise RuntimeError(f"'{ip}' isn't in the local GeoLite2 database (nothing to report).") from e
    except Exception as e:
        raise RuntimeError(f"Local GeoLite2 lookup failed: {e}") from e

    return {
        "lat": record.location.latitude,
        "lon": record.location.longitude,
        "city": record.city.name,
        "region": record.subdivisions.most_specific.name,
        "country": record.country.name,
        "source": "local GeoLite2 database",
    }


def get_coordinates() -> dict:
    """Resolve the current location as raw data: {lat, lon, city, region,
    country, source}. Prefers OS-native location services (Windows/
    macOS), falls back to the local offline MaxMind database. Raises
    RuntimeError with every attempted source's failure reason if nothing
    worked -- callers decide how to present that."""
    system = platform.system()
    errors = []

    if system == "Windows":
        try:
            return _windows_coordinates()
        except RuntimeError as e:
            errors.append(f"Windows Location Services: {e}")
    elif system == "Darwin":
        try:
            return _macos_coordinates()
        except RuntimeError as e:
            errors.append(f"macOS Location Services: {e}")

    try:
        return _maxmind_coordinates()
    except RuntimeError as e:
        errors.append(f"Local GeoLite2 database: {e}")

    raise RuntimeError("\n".join(f"- {e}" for e in errors))


def get_location() -> str:
    """Estimate the machine's current location, preferring OS-native
    location services (Windows/macOS) and falling back to a local,
    offline IP-geolocation database. Never calls a live third-party
    geolocation API directly."""
    try:
        result = get_coordinates()
    except RuntimeError as e:
        return f"Could not determine location:\n{e}"

    parts = [p for p in (result["city"], result["region"], result["country"]) if p]
    place = ", ".join(parts) if parts else "an unknown place"
    return (
        f"Approximate location: {place} "
        f"(approx. {result['lat']}, {result['lon']}) via {result['source']}."
    )


LOCATION_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": (
                "Estimate the current location of this machine, using OS-native "
                "location services on Windows/macOS or a local offline IP-"
                "geolocation database elsewhere. Accuracy varies -- GPS-level on "
                "a laptop with OS location enabled, city-level via the offline "
                "database otherwise."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

LOCATION_TOOL_FUNCTIONS = {"get_location": get_location}

# Read-only -- looking up location never changes anything.
LOCATION_RISKY_TOOLS = set()
