"""Step 14 authentication tests."""

from security.devices import DeviceAuth


def test_pair_and_authenticate(tmp_path):
    auth = DeviceAuth(
        tmp_path / "trusted_devices.json"
    )

    request = auth.request_pairing(
        "jarvis-phone-test",
        "phone",
        "Test Phone",
    )

    token = auth.approve_pending(request)

    device = auth.authenticate(
        "jarvis-phone-test",
        token,
    )

    assert device is not None
    assert device["device_type"] == "phone"

    assert auth.authenticate(
        "jarvis-phone-test",
        "wrong-token",
    ) is None


def test_revoke(tmp_path):
    auth = DeviceAuth(
        tmp_path / "trusted_devices.json"
    )

    request = auth.request_pairing(
        "jarvis-pc-test",
        "pc",
        "Test PC",
    )

    token = auth.approve_pending(request)

    assert auth.authenticate(
        "jarvis-pc-test",
        token,
    )

    assert auth.revoke(
        "jarvis-pc-test"
    )

    assert auth.authenticate(
        "jarvis-pc-test",
        token,
    ) is None
