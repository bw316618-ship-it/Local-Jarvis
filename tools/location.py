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

BASE_DIR = Path(__file__).resolve().parent.parent
GEOIP_DB_PATH = BASE_DIR / "geoip" / "GeoLite2-City.mmdb"

IP_ECHO_URL = "https://api.ipify.org"  # returns plain-text IP only, no location computed server-side
REQUEST_TIMEOUT_SECONDS = 5


def _windows_coordinates() -> dict:
    try:
        import asyncio

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
        civic = coord.civic_address
        city = civic.city if civic else None
        region = civic.state if civic else None
        country = civic.country if civic else None
        return city, region, country, lat, lon

    city, region, country, lat, lon = asyncio.run(_query())
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
        response = requests.get(IP_ECHO_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
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
