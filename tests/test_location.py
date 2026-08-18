"""get_location / get_coordinates: local MaxMind lookup (mocked -- no
real DB shipped or network call in tests), the missing-database message,
public-IP failure handling, and that Linux never attempts the Windows/
macOS branches."""

from unittest.mock import MagicMock, patch

import pytest

import tools.location as loc


def _fake_city_record(city="Boxford", region="West Berkshire", country="United Kingdom", lat=51.75, lon=-1.25):
    record = MagicMock()
    record.city.name = city
    record.subdivisions.most_specific.name = region
    record.country.name = country
    record.location.latitude = lat
    record.location.longitude = lon
    return record


def test_maxmind_coordinates_returns_raw_data(tmp_path, monkeypatch):
    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.write_bytes(b"not a real mmdb -- Reader is mocked below")
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", fake_db)
    monkeypatch.setattr(loc, "_get_public_ip", lambda: "2.125.160.216")

    fake_reader = MagicMock()
    fake_reader.__enter__.return_value.city.return_value = _fake_city_record()
    with patch.object(loc.geoip2.database, "Reader", return_value=fake_reader):
        result = loc._maxmind_coordinates()

    assert result["city"] == "Boxford"
    assert result["region"] == "West Berkshire"
    assert result["country"] == "United Kingdom"
    assert result["lat"] == 51.75 and result["lon"] == -1.25
    assert result["source"] == "local GeoLite2 database"


def test_get_location_formats_the_maxmind_result(tmp_path, monkeypatch):
    monkeypatch.setattr(loc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        loc,
        "_maxmind_coordinates",
        lambda: {"lat": 51.75, "lon": -1.25, "city": "Boxford", "region": "West Berkshire", "country": "United Kingdom", "source": "local GeoLite2 database"},
    )
    result = loc.get_location()
    assert "Boxford" in result and "West Berkshire" in result and "United Kingdom" in result
    assert "51.75" in result and "-1.25" in result


def test_missing_database_gives_clear_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", tmp_path / "does_not_exist.mmdb")
    with pytest.raises(RuntimeError) as exc_info:
        loc._maxmind_coordinates()
    message = str(exc_info.value)
    assert "maxmind.com" in message.lower()
    assert "GeoLite2-City.mmdb" in message


def test_public_ip_failure_is_reported_not_raised_uncaught(tmp_path, monkeypatch):
    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.write_bytes(b"placeholder")
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", fake_db)

    def _boom():
        raise RuntimeError("Could not determine the public IP address: no internet")

    monkeypatch.setattr(loc, "_get_public_ip", _boom)

    with pytest.raises(RuntimeError, match="public IP"):
        loc._maxmind_coordinates()


def test_address_not_found_is_reported_cleanly(tmp_path, monkeypatch):
    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.write_bytes(b"placeholder")
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", fake_db)
    monkeypatch.setattr(loc, "_get_public_ip", lambda: "127.0.0.1")

    fake_reader = MagicMock()
    fake_reader.__enter__.return_value.city.side_effect = loc.geoip2.errors.AddressNotFoundError("not found")
    with patch.object(loc.geoip2.database, "Reader", return_value=fake_reader):
        with pytest.raises(RuntimeError, match="127.0.0.1"):
            loc._maxmind_coordinates()


def test_get_coordinates_on_linux_skips_os_native_and_goes_straight_to_maxmind(monkeypatch):
    """This test suite runs on Linux -- get_coordinates() should never
    even attempt the Windows/macOS branches there."""
    monkeypatch.setattr(loc.platform, "system", lambda: "Linux")
    expected = {"lat": 1.0, "lon": 2.0, "city": "Testville", "region": None, "country": None, "source": "local GeoLite2 database"}
    monkeypatch.setattr(loc, "_maxmind_coordinates", lambda: expected)
    monkeypatch.setattr(
        loc,
        "_windows_coordinates",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called on Linux")),
    )
    monkeypatch.setattr(
        loc,
        "_macos_coordinates",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called on Linux")),
    )

    assert loc.get_coordinates() == expected


def test_get_coordinates_raises_with_all_attempted_sources_on_total_failure(monkeypatch):
    monkeypatch.setattr(loc.platform, "system", lambda: "Windows")
    monkeypatch.setattr(loc, "_windows_coordinates", lambda: (_ for _ in ()).throw(RuntimeError("denied")))
    monkeypatch.setattr(loc, "_maxmind_coordinates", lambda: (_ for _ in ()).throw(RuntimeError("no db")))

    with pytest.raises(RuntimeError) as exc_info:
        loc.get_coordinates()
    message = str(exc_info.value)
    assert "Windows Location Services" in message and "denied" in message
    assert "Local GeoLite2 database" in message and "no db" in message


def test_get_location_surfaces_the_same_failure_as_readable_text(monkeypatch):
    monkeypatch.setattr(loc, "get_coordinates", lambda: (_ for _ in ()).throw(RuntimeError("- everything failed")))
    result = loc.get_location()
    assert "Could not determine location" in result
    assert "everything failed" in result
