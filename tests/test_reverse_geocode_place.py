"""tools.location.reverse_geocode_place -- the richer reverse-geocode
used by the HUD's "click anywhere on the map" feature, distinct from
_reverse_geocode's narrower city/region/country shape used for Jarvis's
own location context.
"""

from unittest.mock import MagicMock, patch

import requests

import tools.location as loc
import tools.net as net


def _fake_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_returns_marker_shape_with_amenity_name():
    payload = {
        "display_name": "Blue Bottle Coffee, 66 Mint St, San Francisco, CA",
        "type": "cafe",
        "class": "amenity",
        "address": {"amenity": "Blue Bottle Coffee", "road": "Mint St"},
    }

    with patch.object(net.requests, "get", return_value=_fake_response(payload)):
        marker = loc.reverse_geocode_place(37.78, -122.41)

    assert marker["name"] == "Blue Bottle Coffee"
    assert marker["address"] == payload["display_name"]
    assert marker["type"] == "cafe"
    assert marker["lat"] == 37.78
    assert marker["lon"] == -122.41


def test_falls_back_through_name_sources_in_order():
    payload = {
        "display_name": "Some Road, Some City",
        "address": {"road": "Some Road"},
    }

    with patch.object(net.requests, "get", return_value=_fake_response(payload)):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert marker["name"] == "Some Road"


def test_falls_back_to_display_name_first_segment_when_no_address_fields():
    payload = {"display_name": "Unnamed Point, District, Country"}

    with patch.object(net.requests, "get", return_value=_fake_response(payload)):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert marker["name"] == "Unnamed Point"


def test_business_only_fields_are_none_not_omitted():
    """A reverse-geocoded address point isn't an Overpass POI, so
    website/phone/opening_hours/cuisine are never available here -- the
    marker shape must still include the keys as None (the frontend
    already only renders truthy fields) rather than omit them, since
    map_agent.js's showDetails() indexes them directly."""
    payload = {"display_name": "A Place", "address": {"road": "A Place"}}

    with patch.object(net.requests, "get", return_value=_fake_response(payload)):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert marker["website"] is None
    assert marker["phone"] is None
    assert marker["opening_hours"] is None
    assert marker["cuisine"] is None
    assert marker["distance_km"] is None


def test_network_failure_returns_error_dict():
    with patch.object(net.requests, "get", side_effect=requests.exceptions.ConnectionError("down")):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert "error" in marker


def test_nominatim_error_payload_returns_error_dict():
    with patch.object(net.requests, "get", return_value=_fake_response({"error": "Unable to geocode"})):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert "error" in marker


def test_empty_payload_returns_error_dict():
    with patch.object(net.requests, "get", return_value=_fake_response({})):
        marker = loc.reverse_geocode_place(1.0, 2.0)

    assert "error" in marker
