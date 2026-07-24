"""Tests for the openFDA HTTP client.

Uses respx to mock httpx at the transport layer so no real openFDA calls
are made. Covers success paths, error paths, api-key injection, and the
retry/backoff behavior for transient failures.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_server_openfda.client import (
    OPENFDA_BASE_URL,
    OpenFDAError,
    OpenFDARateLimitError,
    _backoff_delay,
    query_openfda,
)


# ---------------------------------------------------------------------------
# Response handling: 200, 404, 4xx, 5xx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_query_returns_data_on_200(fixture_loader):
    fixture = fixture_loader("drug_event_pembrolizumab_search")
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json=fixture)
    )

    result = await query_openfda("/drug/event.json", params={"search": "x"})

    assert result == fixture
    assert result["meta"]["results"]["total"] == 26425


@pytest.mark.asyncio
@respx.mock
async def test_query_returns_empty_shape_on_404():
    """openFDA returns 404 for zero-result queries; client normalizes it."""
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(404, text="No matches")
    )

    result = await query_openfda("/drug/event.json", params={"search": "x"})

    assert result == {"meta": {"results": {"total": 0}}, "results": []}


@pytest.mark.asyncio
@respx.mock
async def test_query_raises_openfda_error_on_400():
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(400, text="Bad request: invalid search syntax")
    )

    with pytest.raises(OpenFDAError) as excinfo:
        await query_openfda("/drug/event.json", params={"search": "x"})

    assert "400" in str(excinfo.value)
    assert "invalid search syntax" in str(excinfo.value)


@pytest.mark.asyncio
@respx.mock
async def test_query_raises_openfda_error_on_500_after_retries():
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(500, text="Internal server error")
    )

    with pytest.raises(OpenFDAError):
        await query_openfda(
            "/drug/event.json",
            params={"search": "x"},
            max_retries=0,  # skip retry delay in tests
        )


# ---------------------------------------------------------------------------
# API key injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_query_injects_api_key_from_param():
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    await query_openfda(
        "/drug/event.json",
        params={"search": "x"},
        api_key="my-secret-key",
    )

    called_url = str(route.calls[0].request.url)
    assert "api_key=my-secret-key" in called_url


@pytest.mark.asyncio
@respx.mock
async def test_query_injects_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENFDA_API_KEY", "env-key")
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    await query_openfda("/drug/event.json", params={"search": "x"})

    called_url = str(route.calls[0].request.url)
    assert "api_key=env-key" in called_url


@pytest.mark.asyncio
@respx.mock
async def test_query_omits_api_key_when_absent(monkeypatch):
    monkeypatch.delenv("OPENFDA_API_KEY", raising=False)
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    await query_openfda("/drug/event.json", params={"search": "x"})

    called_url = str(route.calls[0].request.url)
    assert "api_key" not in called_url


@pytest.mark.asyncio
@respx.mock
async def test_query_explicit_api_key_overrides_env(monkeypatch):
    """When both env var and explicit arg are set, explicit arg wins."""
    monkeypatch.setenv("OPENFDA_API_KEY", "env-key")
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    await query_openfda(
        "/drug/event.json",
        params={"search": "x"},
        api_key="explicit-key",
    )

    called_url = str(route.calls[0].request.url)
    assert "api_key=explicit-key" in called_url
    assert "env-key" not in called_url


# ---------------------------------------------------------------------------
# Retry/backoff behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_query_retries_on_429_then_succeeds(monkeypatch):
    """After a 429 the client should sleep, retry, and return the success."""
    # Kill the sleep so the test doesn't actually wait.
    async def instant(*args, **kwargs):
        return None

    monkeypatch.setattr("mcp_server_openfda.client.asyncio.sleep", instant)

    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(429, text="Rate limit"),
            httpx.Response(200, json={"results": [{"ok": True}]}),
        ]
    )

    result = await query_openfda("/drug/event.json", params={"search": "x"})

    assert result == {"results": [{"ok": True}]}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_query_raises_rate_limit_error_after_max_retries(monkeypatch):
    async def instant(*args, **kwargs):
        return None

    monkeypatch.setattr("mcp_server_openfda.client.asyncio.sleep", instant)

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(429, text="Rate limit")
    )

    with pytest.raises(OpenFDARateLimitError) as excinfo:
        await query_openfda(
            "/drug/event.json",
            params={"search": "x"},
            max_retries=2,
        )

    # Error message should point users toward the fix.
    assert "OPENFDA_API_KEY" in str(excinfo.value)


@pytest.mark.asyncio
@respx.mock
async def test_query_retries_on_503(monkeypatch):
    async def instant(*args, **kwargs):
        return None

    monkeypatch.setattr("mcp_server_openfda.client.asyncio.sleep", instant)

    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(503, text="Service unavailable"),
            httpx.Response(200, json={"results": []}),
        ]
    )

    result = await query_openfda("/drug/event.json", params={"search": "x"})

    assert result == {"results": []}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_query_does_not_retry_on_400():
    """Client errors are non-retriable - the request was wrong to begin with."""
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(400, text="Bad request")
    )

    with pytest.raises(OpenFDAError):
        await query_openfda("/drug/event.json", params={"search": "x"})

    # Only one call was made - no retries on 400.
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Backoff calculation
# ---------------------------------------------------------------------------

class TestBackoffDelay:
    def test_grows_exponentially(self):
        # Ignore jitter - check the magnitudes are increasing.
        d0 = _backoff_delay(0)
        d1 = _backoff_delay(1)
        d2 = _backoff_delay(2)
        # With +/- 20% jitter, d1 should still be at least ~1.5x d0.
        assert d1 > d0 * 1.4
        assert d2 > d1 * 1.4

    def test_non_negative(self):
        for attempt in range(5):
            assert _backoff_delay(attempt) >= 0.0

    def test_reasonable_range(self):
        # d0 ~ 1s +/- 20% = [0.8, 1.2]
        d0 = _backoff_delay(0)
        assert 0.7 <= d0 <= 1.3

    def test_rate_limit_error_is_openfda_error(self):
        """Subclass relationship lets callers catch both with one clause."""
        assert issubclass(OpenFDARateLimitError, OpenFDAError)
