"""find_nearby_place (Overpass API) and get_route (OpenRouteService with
OSRM fallback, plus Nominatim geocoding) -- all network calls mocked
with realistic response shapes, no live requests in tests."""

from unittest.mock import MagicMock, patch

import tools.nearby as nb
import tools.routing as rt

LONDON = {"lat": 51.5074, "lon": -0.1278, "city": "London", "region": None, "country": "UK", "source": "test"}


# --- find_nearby_place ----------------------------------------------------

def test_find_nearby_place_sorts_by_distance_and_dedupes(monkeypatch):
    fake_response = {
        "elements": [
            {"type": "node", "lat": 51.5090, "lon": -0.1275, "tags": {"name": "Warren Street", "railway": "station"}},
            {"type": "way", "center": {"lat": 51.5145, "lon": -0.1270}, "tags": {"name": "Euston", "railway": "station"}},
            {"type": "node", "lat": 51.5090, "lon": -0.1275, "tags": {"name": "Warren Street", "railway": "station"}},  # duplicate
            {"type": "node", "lat": 51.5100, "lon": -0.1300, "tags": {}},  # no name -- must be skipped
        ]
    }
    monkeypatch.setattr(nb, "get_coordinates", lambda: LONDON)
    with patch.object(nb.requests, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_response)
        mock_post.return_value.raise_for_status = lambda: None
        result = nb.find_nearby_place("metro station")

    lines = [l for l in result.splitlines() if l.startswith("-")]
    assert len(lines) == 2, "the duplicate and the nameless element must be filtered out"
    assert "Warren Street" in lines[0], "the closer station must be listed first"
    assert "Euston" in lines[1]


def test_find_nearby_place_uses_mapped_tag_filters(monkeypatch):
    monkeypatch.setattr(nb, "get_coordinates", lambda: LONDON)
    with patch.object(nb.requests, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"elements": []})
        mock_post.return_value.raise_for_status = lambda: None
        nb.find_nearby_place("pharmacy")

    query_sent = mock_post.call_args.kwargs["data"]["data"]
    assert 'amenity"="pharmacy"' in query_sent


def test_find_nearby_place_falls_back_to_free_text_for_unmapped_category(monkeypatch):
    monkeypatch.setattr(nb, "get_coordinates", lambda: LONDON)
    with patch.object(nb.requests, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"elements": []})
        mock_post.return_value.raise_for_status = lambda: None
        result = nb.find_nearby_place("Trader Joes")

    query_sent = mock_post.call_args.kwargs["data"]["data"]
    assert 'name"~"trader joes' in query_sent
    assert "No 'Trader Joes' found" in result


def test_find_nearby_place_reports_location_failure_without_calling_overpass(monkeypatch):
    monkeypatch.setattr(nb, "get_coordinates", lambda: (_ for _ in ()).throw(RuntimeError("no db configured")))
    with patch.object(nb.requests, "post") as mock_post:
        result = nb.find_nearby_place("pharmacy")
        assert not mock_post.called, "must not call Overpass if location couldn't be resolved"
    assert "no db configured" in result


def test_find_nearby_place_requires_a_category():
    assert "required" in nb.find_nearby_place("").lower()


# --- get_route --------------------------------------------------------

def test_get_route_via_ors_when_key_configured(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    fake_response = {"routes": [{"summary": {"distance": 1250.5, "duration": 900.0}}]}
    with patch.dict(rt.CONFIG, {"ors_api_key": "fake-key"}):
        with patch.object(rt.requests, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_response)
            mock_post.return_value.raise_for_status = lambda: None
            result = rt.get_route(destination_lat=51.51, destination_lon=-0.12, profile="walking")

    assert "1.25 km" in result and "OpenRouteService" in result


def test_get_route_falls_back_to_osrm_for_driving_without_a_key(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    fake_response = {"code": "Ok", "routes": [{"distance": 5200.0, "duration": 600.0}]}
    with patch.dict(rt.CONFIG, {"ors_api_key": None}):
        with patch.object(rt.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: fake_response)
            mock_get.return_value.raise_for_status = lambda: None
            result = rt.get_route(destination_lat=51.55, destination_lon=-0.10, profile="driving")

    assert "5.20 km" in result and "OSRM" in result


def test_get_route_walking_without_a_key_reports_both_failures(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    with patch.dict(rt.CONFIG, {"ors_api_key": None}):
        result = rt.get_route(destination_lat=51.51, destination_lon=-0.12, profile="walking")

    assert "OpenRouteService" in result and "OSRM" in result
    assert "driving directions" in result  # OSRM's refusal reason must surface


def test_get_route_geocodes_a_destination_name(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    fake_geocode = [{"lat": "48.8584", "lon": "2.2945"}]
    fake_ors = {"routes": [{"summary": {"distance": 1000.0, "duration": 600.0}}]}
    with patch.dict(rt.CONFIG, {"ors_api_key": "fake-key"}):
        with patch.object(rt.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: fake_geocode)
            mock_get.return_value.raise_for_status = lambda: None
            with patch.object(rt.requests, "post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_ors)
                mock_post.return_value.raise_for_status = lambda: None
                result = rt.get_route(destination_name="Eiffel Tower")

    assert "OpenRouteService" in result
    assert mock_get.call_args.kwargs["params"]["q"] == "Eiffel Tower"


def test_get_route_geocode_no_match_is_reported_cleanly(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    with patch.object(rt.requests, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_get.return_value.raise_for_status = lambda: None
        result = rt.get_route(destination_name="Nowhereville Xyzzy")

    assert "No location found" in result


def test_get_route_requires_a_destination(monkeypatch):
    monkeypatch.setattr(rt, "get_coordinates", lambda: LONDON)
    result = rt.get_route()
    assert "destination is required" in result.lower()


def test_get_route_uses_explicit_origin_without_calling_get_coordinates(monkeypatch):
    called = []
    monkeypatch.setattr(rt, "get_coordinates", lambda: called.append(True) or LONDON)
    fake_ors = {"routes": [{"summary": {"distance": 500.0, "duration": 300.0}}]}
    with patch.dict(rt.CONFIG, {"ors_api_key": "fake-key"}):
        with patch.object(rt.requests, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: fake_ors)
            mock_post.return_value.raise_for_status = lambda: None
            rt.get_route(origin_lat=40.0, origin_lon=-73.0, destination_lat=40.1, destination_lon=-73.1)

    assert called == [], "must not resolve current location when an explicit origin is given"
