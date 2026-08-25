"""tools/net.py -- is_retryable classification and request_with_retry's
retry/backoff behavior. No live network calls; requests.get/.post are
mocked throughout."""

from unittest.mock import MagicMock, patch

import requests

import tools.net as net


# --- is_retryable -----------------------------------------------------

def test_timeout_is_retryable():
    assert net.is_retryable(requests.exceptions.Timeout("timed out"))


def test_connection_error_is_retryable():
    assert net.is_retryable(requests.exceptions.ConnectionError("dns failed"))


def test_5xx_http_error_is_retryable():
    response = MagicMock(status_code=503)
    exc = requests.exceptions.HTTPError(response=response)
    assert net.is_retryable(exc)


def test_429_http_error_is_retryable():
    response = MagicMock(status_code=429)
    exc = requests.exceptions.HTTPError(response=response)
    assert net.is_retryable(exc)


def test_404_http_error_is_not_retryable():
    response = MagicMock(status_code=404)
    exc = requests.exceptions.HTTPError(response=response)
    assert not net.is_retryable(exc)


def test_400_http_error_is_not_retryable():
    response = MagicMock(status_code=400)
    exc = requests.exceptions.HTTPError(response=response)
    assert not net.is_retryable(exc)


def test_generic_request_exception_is_not_retryable():
    assert not net.is_retryable(requests.exceptions.URLRequired("bad url"))


# --- request_with_retry -------------------------------------------------

def test_succeeds_first_try_without_retrying(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    ok_response = MagicMock(status_code=200)
    ok_response.raise_for_status.return_value = None

    with patch.object(net.requests, "get", return_value=ok_response) as mock_get:
        result = net.request_with_retry("GET", "https://example.test", timeout=5)

    assert result is ok_response
    assert mock_get.call_count == 1


def test_retries_on_transient_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    ok_response = MagicMock(status_code=200)
    ok_response.raise_for_status.return_value = None

    with patch.object(
        net.requests,
        "get",
        side_effect=[requests.exceptions.ConnectionError("blip"), ok_response],
    ) as mock_get:
        result = net.request_with_retry("GET", "https://example.test", timeout=5)

    assert result is ok_response
    assert mock_get.call_count == 2


def test_gives_up_after_configured_attempts(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)

    with patch.object(
        net.requests,
        "get",
        side_effect=requests.exceptions.ConnectionError("still down"),
    ) as mock_get:
        try:
            net.request_with_retry("GET", "https://example.test", timeout=5, attempts=3)
            assert False, "expected the last exception to be re-raised"
        except requests.exceptions.ConnectionError:
            pass

    assert mock_get.call_count == 3


def test_does_not_retry_a_non_retryable_failure(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    not_found = MagicMock(status_code=404)
    http_error = requests.exceptions.HTTPError(response=not_found)
    bad_response = MagicMock(status_code=404)
    bad_response.raise_for_status.side_effect = http_error

    with patch.object(net.requests, "get", return_value=bad_response) as mock_get:
        try:
            net.request_with_retry("GET", "https://example.test", timeout=5, attempts=3)
            assert False, "expected HTTPError to propagate on first failure"
        except requests.exceptions.HTTPError:
            pass

    assert mock_get.call_count == 1, "a 404 must fail once, not burn through every attempt"


def test_dispatches_post_to_requests_post(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    ok_response = MagicMock(status_code=200)
    ok_response.raise_for_status.return_value = None

    with patch.object(net.requests, "post", return_value=ok_response) as mock_post:
        result = net.request_with_retry("POST", "https://example.test", json={"a": 1})

    assert result is ok_response
    mock_post.assert_called_once_with("https://example.test", json={"a": 1})


def test_attempts_of_one_means_no_retry(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)

    with patch.object(
        net.requests,
        "get",
        side_effect=requests.exceptions.ConnectionError("down"),
    ) as mock_get:
        try:
            net.request_with_retry("GET", "https://example.test", attempts=1)
            assert False, "expected ConnectionError to propagate"
        except requests.exceptions.ConnectionError:
            pass

    assert mock_get.call_count == 1
