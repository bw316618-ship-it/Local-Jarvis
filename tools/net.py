"""
Shared network helper for Jarvis's outbound-HTTP tools (tools/web.py,
tools/weather.py, tools/routing.py, tools/nearby.py, tools/location.py).

Every one of those modules was independently doing
`requests.get(...)` -> `except requests.RequestException` -> wrap into a
RuntimeError/string message. That part was fine and stays the same. What
none of them had was retry: a single dropped packet or a transient 502
from Overpass/Nominatim/Open-Meteo/etc. failed the whole tool call
immediately, even though the same request would likely succeed a second
later.

This module adds exactly two things on top of the existing per-tool
error handling, nothing more:

1. `is_retryable(exc)` -- classifies a requests exception (or an
   already-raised HTTPError from response.raise_for_status()) as worth
   retrying or not. Timeouts, connection failures, and 5xx responses are
   retryable -- something on the wire or the far end had a bad moment.
   4xx responses (bad query, not found, unauthorized) are not -- retrying
   a malformed request just wastes three round trips confirming it's
   still malformed.

2. `request_with_retry(...)` -- a thin wrapper around `requests.request`
   that retries only when `is_retryable` says to, with a short linear
   backoff, and re-raises the *last* exception untouched if every
   attempt fails. Callers keep their existing
   `except requests.RequestException` / `except ValueError` handling
   exactly as before -- this only changes how many times the request is
   attempted before that handling runs, not what it looks like.

Deliberately NOT included: circuit breakers, jittered/exponential
backoff, per-host retry budgets, or any kind of shared state across
calls. Three fixed-interval retries is enough for a single-user local
assistant hitting free public APIs occasionally -- anything fancier is
exactly the kind of premature infrastructure the roadmap already flags
as a recurring risk.
"""

import time

import requests

from config import CONFIG

DEFAULT_ATTEMPTS = CONFIG.get("network_retry_attempts", 3)
DEFAULT_BACKOFF_SECONDS = CONFIG.get("network_retry_backoff_seconds", 0.5)

# 429 (rate limited) is included on the theory that a fixed short backoff
# gives a free-tier API a moment to reset; if that turns out to make
# rate-limiting worse in practice for a given service, drop 429 from this
# set for that caller rather than globally.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable(exc: Exception) -> bool:
    """True if `exc` (raised by requests, or an HTTPError from
    response.raise_for_status()) represents a transient failure worth
    retrying rather than a request that will never succeed."""
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True

    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        status = getattr(response, "status_code", None)
        return status in _RETRYABLE_STATUS_CODES

    # Anything else -- bad URL, too-many-redirects, a non-HTTP
    # RequestException subclass we haven't seen -- treat as permanent.
    return False


def request_with_retry(
    method: str,
    url: str,
    *,
    attempts: int = None,
    backoff_seconds: float = None,
    **kwargs,
) -> requests.Response:
    """`requests.request(method, url, **kwargs)`, retried on transient
    failures per `is_retryable`. Raises `response.raise_for_status()`
    itself when the response is present but not OK, so a 4xx/5xx is
    classified the same way whether it arrived as an HTTPError from a
    prior raise or is being checked here for the first time.

    On exhausting all attempts, re-raises the last exception as-is --
    callers keep their existing `except requests.RequestException`
    handling unchanged.
    """
    attempts = attempts if attempts is not None else DEFAULT_ATTEMPTS
    backoff_seconds = backoff_seconds if backoff_seconds is not None else DEFAULT_BACKOFF_SECONDS
    attempts = max(1, attempts)

    # Dispatched via requests.get/requests.post (rather than the single
    # requests.request entry point) so this lines up with how every
    # caller here already talked to `requests` directly, and so tests
    # can patch tools.net.requests.get/.post the same way they were
    # already patching <module>.requests.get/.post before this helper
    # existed.
    verb = getattr(requests, method.lower())

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            response = verb(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < attempts and is_retryable(exc):
                time.sleep(backoff_seconds * attempt)
                continue
            raise

    # Unreachable (loop always returns or raises), but keeps type
    # checkers happy and fails loudly instead of returning None if the
    # loop logic above is ever changed.
    raise last_exc
