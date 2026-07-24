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
    calculate_reporting_odds_ratio,
    count_adverse_events,
    count_reactions,
    get_drug_label,
    search_drug_adverse_events,
    search_drug_recalls,
)


def _totals_response(total: int) -> dict:
    """Build a minimal openFDA response that only carries the total count."""
    return {"meta": {"results": {"total": total}}, "results": []}


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
async def test_search_lay_term_includes_reaction_expansion_metadata(fixture_loader):
    """When 'headache' is passed, response should surface the expansion."""
    page = fixture_loader("drug_event_pembrolizumab_search")
    counts = fixture_loader("drug_event_count_reactions")

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=page),
            httpx.Response(200, json=counts),
        ]
    )

    result = await search_drug_adverse_events(
        drug_name="pembrolizumab", reaction="headache", limit=2
    )

    assert "reaction_expansion" in result
    expansion = result["reaction_expansion"]
    assert expansion["original_term"] == "headache"
    assert "Headache" in expansion["expanded_to_meddra_pts"]
    assert "note" in expansion


@pytest.mark.asyncio
@respx.mock
async def test_search_meddra_pt_omits_expansion_metadata(fixture_loader):
    """A canonical MedDRA PT (not in lay dict) passes through without expansion."""
    page = fixture_loader("drug_event_pembrolizumab_search")
    counts = fixture_loader("drug_event_count_reactions")

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(
        side_effect=[
            httpx.Response(200, json=page),
            httpx.Response(200, json=counts),
        ]
    )

    result = await search_drug_adverse_events(
        drug_name="pembrolizumab",
        reaction="Cardiac tamponade",  # not in lay-term dictionary
        limit=2,
    )

    # Passed through unchanged - no expansion field on response.
    assert "reaction_expansion" not in result


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
async def test_get_drug_label_forwards_manufacturer_filter(fixture_loader):
    """When manufacturer is passed, the openFDA request should include it."""
    label = fixture_loader("drug_label_pembrolizumab")

    route = respx.get(f"{OPENFDA_BASE_URL}/drug/label.json").mock(
        return_value=httpx.Response(200, json=label)
    )

    await get_drug_label(
        drug_name="pembrolizumab",
        manufacturer="Merck Sharp & Dohme LLC",
    )

    called_url = str(route.calls[0].request.url)
    # Manufacturer name should appear (URL-encoded) in the request.
    assert "manufacturer_name" in called_url
    assert "Merck" in called_url


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


# ---------------------------------------------------------------------------
# calculate_reporting_odds_ratio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_ror_happy_path_positive_signal():
    """Mock 4 totals that yield ROR = 20 (strong positive signal)."""
    # Order matters: asyncio.gather issues them in this order:
    #   drug + reaction (a=100)
    #   drug only (n_ax=1100)
    #   reaction only (n_xr=600)
    #   all reports (n=101600)
    # But respx side_effect matches requests to routes in URL/query order,
    # not caller order. To keep the test deterministic, mock ALL calls to
    # the endpoint with the same response cycle regardless of order and
    # verify the final numbers - the arithmetic doesn't care which route
    # fired which count as long as they're consistent.
    #
    # For simplicity we mock each of the four queries to return a fixed
    # total; the .gather() call will get whichever total maps to whichever
    # query. That's brittle to reorder, so we use a more resilient approach:
    # respx.route(url=...).mock() supports named routes, but even simpler:
    # since all four calls hit /drug/event.json, we return a callable that
    # dispatches on the query string.
    def dispatch(request):
        query = request.url.params.get("search", "")
        # drug + reaction: has BOTH patient.drug.openfda AND reactionmeddrapt
        if "patient.drug.openfda" in query and "reactionmeddrapt" in query:
            return httpx.Response(200, json=_totals_response(100))
        # drug only: has patient.drug.openfda, NO reactionmeddrapt
        if "patient.drug.openfda" in query and "reactionmeddrapt" not in query:
            return httpx.Response(200, json=_totals_response(1100))
        # reaction only: has reactionmeddrapt, no patient.drug.openfda
        if "reactionmeddrapt" in query and "patient.drug.openfda" not in query:
            return httpx.Response(200, json=_totals_response(600))
        # all reports: just receivedate range
        return httpx.Response(200, json=_totals_response(101600))

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(side_effect=dispatch)

    result = await calculate_reporting_odds_ratio(
        drug_name="pembrolizumab", reaction="Pneumonitis"
    )

    assert result["contingency_table"]["a_drug_and_reaction"] == 100
    assert result["totals"]["reports_with_drug"] == 1100
    assert result["totals"]["reports_with_reaction"] == 600
    assert result["totals"]["reports_total"] == 101600
    # ROR = (100 * 100000) / (1000 * 500) = 20
    assert result["ror"] == pytest.approx(20.0, rel=1e-6)
    assert result["signal"] is True
    assert result["ci_95_lower"] > 1.0


@pytest.mark.asyncio
@respx.mock
async def test_ror_zero_co_reports_returns_no_signal():
    """When a = 0, ROR = 0 and signal = False."""
    def dispatch(request):
        query = request.url.params.get("search", "")
        if "patient.drug.openfda" in query and "reactionmeddrapt" in query:
            return httpx.Response(200, json=_totals_response(0))  # a = 0
        if "patient.drug.openfda" in query:
            return httpx.Response(200, json=_totals_response(500))
        if "reactionmeddrapt" in query:
            return httpx.Response(200, json=_totals_response(1000))
        return httpx.Response(200, json=_totals_response(100000))

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(side_effect=dispatch)

    result = await calculate_reporting_odds_ratio(
        drug_name="pembrolizumab", reaction="Pneumonitis"
    )

    assert result["ror"] == 0.0
    assert result["signal"] is False
    assert "notes" in result


@pytest.mark.asyncio
@respx.mock
async def test_ror_forwards_reaction_expansion_metadata():
    """When a lay term is passed, response should include expansion metadata."""
    def dispatch(request):
        return httpx.Response(200, json=_totals_response(100))

    respx.get(f"{OPENFDA_BASE_URL}/drug/event.json").mock(side_effect=dispatch)

    result = await calculate_reporting_odds_ratio(
        drug_name="pembrolizumab", reaction="headache"
    )

    assert "reaction_expansion" in result
    assert result["reaction_expansion"]["original_term"] == "headache"
