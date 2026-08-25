from unittest.mock import Mock, patch

import tools.net as net
import tools.weather as weather


def test_get_weather_uses_current_coordinates():
    location = {
        "lat": 28.56307,
        "lon": 77.28851,
        "city": "Delhi",
        "region": "Delhi",
        "country": "India",
        "source": "Windows Location Services",
    }

    payload = {
        "current": {
            "time": "2026-08-17T20:00",
            "temperature_2m": 31.0,
            "relative_humidity_2m": 65,
            "apparent_temperature": 35.0,
            "precipitation": 0.0,
            "rain": 0.0,
            "weather_code": 2,
            "cloud_cover": 40,
            "wind_speed_10m": 8.0,
            "wind_direction_10m": 180,
        },
        "current_units": {
            "temperature_2m": "°C",
            "wind_speed_10m": "km/h",
        },
        "hourly": {
            "time": ["2026-08-17T20:00", "2026-08-17T21:00"],
            "precipitation_probability": [10, 15],
        },
        "timezone": "Asia/Kolkata",
    }

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload

    with patch.object(weather, "get_coordinates", return_value=location):
        with patch.object(net.requests, "get", return_value=response) as request:
            result = weather.get_weather()

    assert "31" in result
    assert "Delhi" in result
    assert "28.56307" in result
    assert request.call_args.kwargs["params"]["latitude"] == location["lat"]
    assert request.call_args.kwargs["params"]["longitude"] == location["lon"]
