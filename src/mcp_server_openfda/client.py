"""openFDA HTTP client.

A thin async wrapper around httpx for talking to api.fda.gov. The client
deliberately stays narrow: one function (query_openfda) that handles the
HTTP concerns (URL, auth, timeout, error normalization), and lets each
MCP tool build its own openFDA query string.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

OPENFDA_BASE_URL = "https://api.fda.gov"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenFDAError(Exception):
    """Raised when openFDA returns an HTTP error other than 404.

    404 is treated as 'no results' rather than an error because openFDA
    returns 404 (not 200 with an empty array) when a search yields zero
    matches. We translate that into an empty result shape upstream.
    """


async def query_openfda(
    endpoint: str,
    params: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    """Call an openFDA endpoint and return the parsed JSON response.

    Args:
        endpoint: Path under api.fda.gov, e.g. "/drug/event.json".
        params: Query parameters in dict form (search, count, limit, skip, ...).
            Do not include api_key here; it's added automatically.
        api_key: Optional explicit override. If None, falls back to the
            OPENFDA_API_KEY environment variable. Without a key the public
            limit is ~240 req/min; with a key it's ~120,000 req/day.

    Returns:
        The parsed JSON body. On HTTP 404 (openFDA's "no results" response)
        returns the canonical empty shape:
            {"meta": {"results": {"total": 0}}, "results": []}

    Raises:
        OpenFDAError: For any non-200, non-404 HTTP response.
        httpx.RequestError: For network-level failures (DNS, timeout, etc.)
            propagated unchanged so callers can distinguish transport
            failures from API errors.
    """
    key = api_key if api_key is not None else os.environ.get("OPENFDA_API_KEY")
    request_params = dict(params)
    if key:
        request_params["api_key"] = key

    url = f"{OPENFDA_BASE_URL}{endpoint}"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(url, params=request_params)

    if response.status_code == 404:
        # openFDA's empty-result convention.
        return {"meta": {"results": {"total": 0}}, "results": []}

    if response.status_code != 200:
        # Truncate the body so an HTML error page doesn't blow up the
        # exception message in the LLM's view.
        body_excerpt = response.text[:500]
        raise OpenFDAError(
            f"openFDA returned HTTP {response.status_code} for "
            f"{endpoint}: {body_excerpt}"
        )

    return response.json()
