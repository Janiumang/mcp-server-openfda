"""Shared pytest fixtures for the mcp-server-openfda test suite.

The suite uses recorded openFDA response fixtures stored as JSON files in
tests/fixtures/openfda/. Each test that hits the client layer patches
httpx via respx (see individual test modules) and returns one of these
fixtures instead of a live API call. That gives us:

    - Deterministic tests (same response every run)
    - Fast CI (no network in the test path)
    - Real API response shapes (fixtures are captured from live openFDA)

If openFDA changes a response shape upstream, fixtures may drift and
tests will still pass while production breaks. To mitigate: refresh
fixtures periodically by capturing new real responses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Directory containing the JSON fixture files.
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "openfda"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from tests/fixtures/openfda/ by name (no extension).

    Example: load_fixture("drug_event_pembrolizumab") reads
    tests/fixtures/openfda/drug_event_pembrolizumab.json.
    """
    path = FIXTURES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture not found: {path}. "
            "Available fixtures: "
            f"{sorted(p.stem for p in FIXTURES_DIR.glob('*.json'))}"
        )
    with path.open() as f:
        return json.load(f)


@pytest.fixture
def fixture_loader():
    """Return the load_fixture helper as a test fixture.

    Use this in tests to load response fixtures without importing the
    helper directly:
        def test_something(fixture_loader):
            data = fixture_loader("drug_event_pembrolizumab")
    """
    return load_fixture
