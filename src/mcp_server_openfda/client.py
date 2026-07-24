"""openFDA HTTP client.

A thin async wrapper around httpx for talking to api.fda.gov. The client
deliberately stays narrow: one function (query_openfda) that handles the
HTTP concerns (URL, auth, timeout, retry, error normalization) and lets
each MCP tool build its own openFDA query string.

Retry policy:
    Requests are retried up to MAX_RETRIES times for transient failures
    (HTTP 429 rate limit, 502/503/504 server errors). Backoff is
    exponential (1s, 2s, 4s) with a small jitter. Non-retriable errors
    (4xx client errors other than 429) raise immediately.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any

import httpx

OPENFDA_BASE_URL = "https://api.fda.gov"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Transient HTTP statuses that trigger a retry. 429 = rate limit,
# 502/503/504 = intermittent server-side issues.
_RETRIABLE_STATUS_CODES: frozenset[int] = frozenset({429, 502, 503, 504})

MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0


class OpenFDAError(Exception):
    """Raised when openFDA returns an HTTP error other than 404.

    404 is treated as 'no results' rather than an error because openFDA
    returns 404 (not 200 with an empty array) when a search yields zero
    matches. We translate that into an empty result shape upstream.
    """


class OpenFDARateLimitError(OpenFDAError):
    """Raised when openFDA returns 429 after all retries are exhausted.

    Distinct from OpenFDAError so callers can surface a specific
    'try again later or add an OPENFDA_API_KEY' message to end users.
    """


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with small random jitter.

    attempt is zero-indexed: 0 -> ~1s, 1 -> ~2s, 2 -> ~4s. Jitter is
    +/- 20% to spread retries across concurrent callers if we ever
    have many at once.
    """
    base = _BACKOFF_BASE_SECONDS * (2**attempt)
    jitter = base * random.uniform(-0.2, 0.2)
    return max(0.0, base + jitter)


async def query_openfda(
    endpoint: str,
    params: dict[str, Any],
    api_key: str | None = None,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Call an openFDA endpoint and return the parsed JSON response.

    Args:
        endpoint: Path under api.fda.gov, e.g. "/drug/event.json".
        params: Query parameters in dict form (search, count, limit, skip,
            ...). Do not include api_key here; it is added automatically.
        api_key: Optional explicit override. If None, falls back to the
            OPENFDA_API_KEY environment variable. Without a key the public
            limit is ~240 req/min; with a key it's ~120,000 req/day.
        max_retries: Override the default retry ceiling. Testing hook.

    Returns:
        The parsed JSON body. On HTTP 404 returns the canonical empty
        result shape: {"meta": {"results": {"total": 0}}, "results": []}.

    Raises:
        OpenFDARateLimitError: All retries exhausted while hitting 429.
        OpenFDAError: A non-retriable HTTP error (400/401/403/500 etc.)
            or a retriable error that exhausted retries.
        httpx.RequestError: Network-level failures (DNS, timeout) are
            propagated unchanged so callers can distinguish transport
            failures from API errors.
    """
    key = api_key if api_key is not None else os.environ.get("OPENFDA_API_KEY")
    request_params = dict(params)
    if key:
        request_params["api_key"] = key

    url = f"{OPENFDA_BASE_URL}{endpoint}"
    last_response: httpx.Response | None = None

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        for attempt in range(max_retries + 1):
            response = await client.get(url, params=request_params)
            last_response = response

            if response.status_code == 200:
                return response.json()

            if response.status_code == 404:
                return {"meta": {"results": {"total": 0}}, "results": []}

            if (
                response.status_code in _RETRIABLE_STATUS_CODES
                and attempt < max_retries
            ):
                await asyncio.sleep(_backoff_delay(attempt))
                continue

            # Non-retriable, or retries exhausted.
            body_excerpt = response.text[:500]
            if response.status_code == 429:
                raise OpenFDARateLimitError(
                    f"openFDA rate limit exceeded on {endpoint} after "
                    f"{attempt + 1} attempts. Consider setting an "
                    f"OPENFDA_API_KEY to raise the limit. Body: {body_excerpt}"
                )
            raise OpenFDAError(
                f"openFDA returned HTTP {response.status_code} for "
                f"{endpoint}: {body_excerpt}"
            )

    # Should be unreachable - the loop either returns, sleeps, or raises.
    # Included so type checkers see all paths return.
    assert last_response is not None
    raise OpenFDAError(
        f"openFDA request to {endpoint} failed after {max_retries} retries."
    )
