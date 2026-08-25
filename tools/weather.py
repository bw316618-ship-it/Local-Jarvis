"""
Live weather for Jarvis using the computer's current coordinates.

Uses tools.location.get_coordinates() for the exact OS-provided location and
Open-Meteo for current conditions/forecast. No API key is required.

Read-only.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from tools.location import get_coordinates
from tools.net import request_with_retry

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 10

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _fmt(value, suffix=""):
    if value is None:
        return "unknown"
    return f"{value:.0f}{suffix}"


def get_weather() -> str:
    """Get current weather at the computer's current location."""
    try:
        here = get_coordinates()
    except RuntimeError as exc:
        return f"Could not determine current location:\n{exc}"

    params = {
        "latitude": here["lat"],
        "longitude": here["lon"],
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "hourly": ",".join(
            [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "weather_code",
            ]
        ),
        "forecast_days": 1,
        "timezone": "auto",
    }

    try:
        response = request_with_retry(
            "GET",
            OPEN_METEO_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "Local-Jarvis/1.0"},
        )
        data = response.json()
    except requests.RequestException as exc:
        return f"Weather lookup failed: {exc}"
    except ValueError:
        return "Weather lookup failed: the weather service returned invalid JSON."

    current = data.get("current", {})
    units = data.get("current_units", {})
    code = current.get("weather_code")
    description = WEATHER_CODES.get(code, f"weather code {code}")

    temperature = current.get("temperature_2m")
    feels_like = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    precip = current.get("precipitation")
    rain = current.get("rain")

    temp_unit = units.get("temperature_2m", "°C")
    wind_unit = units.get("wind_speed_10m", "km/h")

    location_parts = [
        here.get("city"),
        here.get("region"),
        here.get("country"),
    ]
    place = ", ".join(p for p in location_parts if p) or "your current location"

    lines = [
        f"Weather at {place} ({here['lat']:.5f}, {here['lon']:.5f}):",
        f"- {description.capitalize()}, {_fmt(temperature)}{temp_unit}; feels like {_fmt(feels_like)}{temp_unit}",
        f"- Humidity: {_fmt(humidity, '%')}",
        f"- Wind: {_fmt(wind)} {wind_unit}",
        f"- Precipitation: {precip if precip is not None else 'unknown'} mm",
        f"- Rain: {rain if rain is not None else 'unknown'} mm",
    ]

    # Add the next few hourly precipitation probabilities.
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    probs = hourly.get("precipitation_probability", [])
    if times and probs:
        try:
            current_time = datetime.fromisoformat(
                str(current.get("time", "")).replace("Z", "+00:00")
            )
            next_points = []
            for timestamp, probability in zip(times, probs):
                dt = datetime.fromisoformat(str(timestamp))
                if dt.tzinfo is None and data.get("timezone"):
                    dt = dt.replace(tzinfo=ZoneInfo(data["timezone"]))
                if dt >= current_time.replace(tzinfo=None) and probability is not None:
                    next_points.append((timestamp, probability))
                if len(next_points) == 3:
                    break
            if next_points:
                lines.append(
                    "- Rain probability next hours: "
                    + ", ".join(f"{ts[11:16]} {prob}%" for ts, prob in next_points)
                )
        except (ValueError, TypeError):
            pass

    return "\n".join(lines)


WEATHER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "MANDATORY TOOL for current weather requests. "
                "Use the computer's current location automatically. "
                "Use this for requests such as 'what is the weather', "
                "'is it raining here', 'how hot is it outside', or 'weather near me'. "
                "Do not answer current-weather questions from general knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

WEATHER_TOOL_FUNCTIONS = {"get_weather": get_weather}
WEATHER_RISKY_TOOLS = set()
