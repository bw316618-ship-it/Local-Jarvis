"""get_location: local MaxMind lookup (mocked -- no real DB shipped or
network call in tests), the missing-database message, public-IP failure
handling, and that Linux never attempts the Windows/macOS branches."""

from unittest.mock import MagicMock, patch

import tools.location as loc


def _fake_city_record(city="Boxford", region="West Berkshire", country="United Kingdom", lat=51.75, lon=-1.25):
    record = MagicMock()
    record.city.name = city
    record.subdivisions.most_specific.name = region
    record.country.name = country
    record.location.latitude = lat
    record.location.longitude = lon
    return record


def test_maxmind_location_formats_a_full_result(tmp_path, monkeypatch):
    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.write_bytes(b"not a real mmdb -- Reader is mocked below")
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", fake_db)
    monkeypatch.setattr(loc, "_get_public_ip", lambda: "2.125.160.216")

    fake_reader = MagicMock()
    fake_reader.__enter__.return_value.city.return_value = _fake_city_record()
    with patch.object(loc.geoip2.database, "Reader", return_value=fake_reader):
        result = loc._maxmind_location()

    assert "Boxford" in result
    assert "West Berkshire" in result
    assert "United Kingdom" in result
    assert "51.75" in result and "-1.25" in result
    assert "local GeoLite2 database" in result


def test_missing_database_gives_clear_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", tmp_path / "does_not_exist.mmdb")
    with __import__("pytest").raises(RuntimeError) as exc_info:
        loc._maxmind_location()
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

    try:
        loc._maxmind_location()
        assert False, "should have raised"
    except RuntimeError as e:
        assert "public IP" in str(e)


def test_address_not_found_is_reported_cleanly(tmp_path, monkeypatch):
    fake_db = tmp_path / "GeoLite2-City.mmdb"
    fake_db.write_bytes(b"placeholder")
    monkeypatch.setattr(loc, "GEOIP_DB_PATH", fake_db)
    monkeypatch.setattr(loc, "_get_public_ip", lambda: "127.0.0.1")

    fake_reader = MagicMock()
    fake_reader.__enter__.return_value.city.side_effect = loc.geoip2.errors.AddressNotFoundError("not found")
    with patch.object(loc.geoip2.database, "Reader", return_value=fake_reader):
        try:
            loc._maxmind_location()
            assert False, "should have raised"
        except RuntimeError as e:
            assert "127.0.0.1" in str(e)


def test_get_location_on_linux_skips_os_native_and_goes_straight_to_maxmind(monkeypatch):
    """This test suite runs on Linux -- get_location() should never even
    attempt the Windows/macOS branches there, and should surface the
    MaxMind result (or its error) directly."""
    monkeypatch.setattr(loc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(loc, "_maxmind_location", lambda: "Approximate location: Testville via local GeoLite2 database.")
    monkeypatch.setattr(
        loc,
        "_windows_location",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called on Linux")),
    )
    monkeypatch.setattr(
        loc,
        "_macos_location",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called on Linux")),
    )

    assert loc.get_location() == "Approximate location: Testville via local GeoLite2 database."


def test_get_location_reports_all_attempted_sources_on_total_failure(monkeypatch):
    monkeypatch.setattr(loc.platform, "system", lambda: "Windows")
    monkeypatch.setattr(loc, "_windows_location", lambda: (_ for _ in ()).throw(RuntimeError("denied")))
    monkeypatch.setattr(loc, "_maxmind_location", lambda: (_ for _ in ()).throw(RuntimeError("no db")))

    result = loc.get_location()
    assert "Windows Location Services" in result and "denied" in result
    assert "Local GeoLite2 database" in result and "no db" in result
