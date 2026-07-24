"""Integration tests for the six MCP tools defined in server.py.

Each test mocks openFDA at the HTTP layer with respx, exercises the tool
function directly (bypassing the MCP wire protocol - we're testing the
Python logic, not the JSON-RPC framing), and asserts on the shape and
contents of the response.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_server_openfda.client import OPENFDA_BASE_URL
from mcp_server_openfda.server import (
    count_adverse_events,
    count_reactions,
    get_drug_label,
    search_drug_adverse_events,
    search_drug_recalls,
)


# ---------------------------------------------------------------------------
# search_drug_adverse_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_search_returns_records_and_narrowing_hint(fixture_loader):
    page = fixture_loader("drug_event_pembrolizumab_search")
    counts = fixture_loader("drug_event_count_reactions")

    # First call: the page query. Second call: the top-reactions count query.
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=page),
            httpx.Response(200, json=counts),
        ]
    )

    result = await search_drug_adverse_events(
        drug_name="pembrolizumab", limit=2
    )

    assert result["total_matching"] == 26425
    assert result["returned"] == 2
    assert len(result["records"]) == 2
    # First record is tidied: female, physician->consumer etc.
    assert result["records"][0]["patient_sex"] == "Female"
    assert result["records"][0]["serious"] is True

    # Top reactions come through the count query, normalized case.
    labels = [r["term"] for r in result["top_reactions"]]
    assert "Diarrhoea" in labels
    assert "Malignant neoplasm progression" in labels

    # Narrowing hint fires because total (26,425) > limit (2).
    assert "narrowing_hint" in result
    assert "Diarrhoea" in result["narrowing_hint"]


@pytest.mark.asyncio
@respx.mock
async def test_search_zero_results_skips_count_query(fixture_loader):
    """When the page query returns empty, don't waste the count round trip."""
    empty = fixture_loader("drug_event_empty")

    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        return_value=httpx.Response(200, json=empty)
    )

    result = await search_drug_adverse_events(drug_name="nonexistent-drug")

    assert result["total_matching"] == 0
    assert result["returned"] == 0
    assert result["top_reactions"] == []
    # Only one call - not the count follow-up.
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# count_adverse_events + count_reactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_count_adverse_events_reaction_pivot(fixture_loader):
    counts = fixture_loader("drug_event_count_reactions")
    total = {"meta": {"results": {"total": 100000}}, "results": []}

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=total),  # total query
            httpx.Response(200, json=counts),  # count query
        ]
    )

    result = await count_adverse_events(
        drug_name="pembrolizumab", pivot="reaction", limit=5
    )

    assert result["pivot"] == "reaction"
    assert result["total_matching"] == 100000
    assert len(result["counts"]) == 5
    assert result["counts"][0]["label"] == "Malignant neoplasm progression"
    assert result["counts"][0]["count"] == 2619


@pytest.mark.asyncio
@respx.mock
async def test_count_reactions_shortcut_equivalence(fixture_loader):
    """count_reactions should return the same shape as pivot='reaction'."""
    counts = fixture_loader("drug_event_count_reactions")
    total = {"meta": {"results": {"total": 100000}}, "results": []}

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=total),
            httpx.Response(200, json=counts),
        ]
    )

    result = await count_reactions(drug_name="pembrolizumab", limit=5)

    assert result["pivot"] == "reaction"
    assert result["total_matching"] == 100000
    assert result["counts"][0]["label"] == "Malignant neoplasm progression"


@pytest.mark.asyncio
@respx.mock
async def test_count_adverse_events_country_pivot(fixture_loader):
    counts = fixture_loader("drug_event_count_countries")
    total = {"meta": {"results": {"total": 100000}}, "results": []}

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=total),
            httpx.Response(200, json=counts),
        ]
    )

    result = await count_adverse_events(
        drug_name="pembrolizumab", pivot="country", limit=5
    )

    assert result["counts"][0]["label"] == "US"
    assert result["counts"][0]["count"] == 31839


@pytest.mark.asyncio
@respx.mock
async def test_count_adverse_events_qualification_pivot_translates(fixture_loader):
    """reporter_qualification pivot should translate ICH E2B codes to labels."""
    counts = fixture_loader("drug_event_count_qualifications")
    total = {"meta": {"results": {"total": 100000}}, "results": []}

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=total),
            httpx.Response(200, json=counts),
        ]
    )

    result = await count_adverse_events(
        drug_name="pembrolizumab", pivot="reporter_qualification", limit=5
    )

    labels = {c["label"] for c in result["counts"]}
    assert "Physician" in labels
    assert "Consumer or non-health professional" in labels


@pytest.mark.asyncio
@respx.mock
async def test_count_adverse_events_seriousness_subtype(fixture_loader):
    """seriousness_subtype pivot runs six concurrent count queries."""
    death_only = fixture_loader("drug_event_seriousness_death")
    total = {"meta": {"results": {"total": 100000}}, "results": []}

    # First call: total. Then six seriousness subtype queries, all returning
    # the same "1"-count fixture for simplicity.
    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=total),
        ]
        + [httpx.Response(200, json=death_only) for _ in range(6)]
    )

    result = await count_adverse_events(
        drug_name="pembrolizumab", pivot="seriousness_subtype"
    )

    assert result["pivot"] == "seriousness_subtype"
    assert len(result["counts"]) == 6  # Death, Life-threatening, Hosp, etc.
    labels = {c["label"] for c in result["counts"]}
    assert "Death" in labels
    assert "Hospitalization" in labels


@pytest.mark.asyncio
@respx.mock
async def test_count_adverse_events_invalid_pivot_returns_error():
    """Invalid pivot never hits openFDA - returns a helpful error dict."""
    route = respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock()

    result = await count_adverse_events(
        drug_name="pembrolizumab", pivot="bogus_pivot"
    )

    assert "error" in result
    assert "bogus_pivot" in result["error"]
    assert "valid_pivots" in result
    assert route.call_count == 0  # never touched openFDA


# ---------------------------------------------------------------------------
# get_drug_label
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_happy_path(fixture_loader):
    label = fixture_loader("drug_label_pembrolizumab")

    respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=label)
    )

    result = await get_drug_label(drug_name="pembrolizumab")

    assert result["drug_name_query"] == "pembrolizumab"
    assert result["label_metadata"]["effective_time"] == "2026-04-06"
    assert result["label_metadata"]["application_number"] == ["BLA125514"]
    # Contents present
    assert "KEYTRUDA" in result["sections"]["indications_and_usage"]


@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_absent_sections_return_null(fixture_loader):
    """Sections not in the label come back as null, not missing."""
    label = fixture_loader("drug_label_pembrolizumab")

    respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=label)
    )

    result = await get_drug_label(drug_name="pembrolizumab")

    # boxed_warning and drug_interactions are absent in the fixture.
    assert result["sections"]["boxed_warning"] is None
    assert result["sections"]["drug_interactions"] is None


@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_truncates_long_sections():
    """Sections exceeding max_section_chars are truncated with a recovery note."""
    big_text = "A" * 20000
    fake_label = {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "effective_time": "20260101",
                "openfda": {
                    "generic_name": ["ASPIRIN"],
                    "brand_name": ["ASPIRIN"],
                    "substance_name": ["ASPIRIN"],
                },
                "adverse_reactions": [big_text],
            }
        ],
    }

    respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=fake_label)
    )

    result = await get_drug_label(drug_name="aspirin", max_section_chars=1000)

    ar = result["sections"]["adverse_reactions"]
    assert ar.startswith("A" * 1000)
    assert "Section truncated" in ar
    assert "sections=['adverse_reactions']" in ar


@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_not_found():
    """openFDA returns an empty result for unknown drugs; tool surfaces error."""
    empty = {"meta": {"results": {"total": 0}}, "results": []}

    respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=empty)
    )

    result = await get_drug_label(drug_name="not-a-real-drug")

    assert "error" in result
    assert "No FDA label found" in result["error"]


@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_sections_filter(fixture_loader):
    """Passing sections=[...] returns only the requested subset."""
    label = fixture_loader("drug_label_pembrolizumab")

    respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=label)
    )

    result = await get_drug_label(
        drug_name="pembrolizumab",
        sections=["contraindications", "adverse_reactions"],
    )

    assert set(result["sections"].keys()) == {"contraindications", "adverse_reactions"}


@pytest.mark.asyncio
@respx.mock
async def test_get_drug_label_invalid_section_name():
    """Unknown section names return an error listing valid ones."""
    result = await get_drug_label(
        drug_name="pembrolizumab", sections=["not_a_real_section"]
    )

    assert "error" in result
    assert "valid_sections" in result


# ---------------------------------------------------------------------------
# search_drug_recalls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_search_recalls_by_firm(fixture_loader):
    recalls = fixture_loader("drug_enforcement_pfizer")

    respx.get(f"{OPENFDA_BASE_URL}/drug/enforcement.json").mock(
        return_value=httpx.Response(200, json=recalls)
    )

    result = await search_drug_recalls(firm="Pfizer", limit=2)

    assert result["firm_query"] == "Pfizer"
    assert result["total_matching"] == 155
    assert result["returned"] == 2
    # Tidied records include class_description
    assert result["records"][0]["classification"] == "Class II"
    assert "medically reversible" in result["records"][0]["class_description"]
    assert result["records"][0]["recall_initiation_date"] == "2025-08-04"


@pytest.mark.asyncio
async def test_search_recalls_requires_drug_or_firm():
    """Neither drug_name nor firm should return an actionable error."""
    result = await search_drug_recalls()

    assert "error" in result
    assert "drug_name or firm" in result["error"]


@pytest.mark.asyncio
async def test_search_recalls_invalid_classification():
    result = await search_drug_recalls(
        drug_name="metformin", classification="Class IV"
    )

    assert "error" in result
    assert "valid_classifications" in result
    assert "Class I" in result["valid_classifications"]


@pytest.mark.asyncio
async def test_search_recalls_invalid_status():
    result = await search_drug_recalls(
        drug_name="metformin", status="MadeUp"
    )

    assert "error" in result
    assert "valid_statuses" in result
