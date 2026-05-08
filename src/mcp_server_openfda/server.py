"""SignalBridge for openFDA - MCP server entry point.

v0.1 in progress. Currently exposes:
    - ping: trivial wiring check
    - search_drug_adverse_events: FAERS report search with PV-aware filters

Still to come for v0.1:
    - count_adverse_events
    - get_drug_label
    - search_drug_recalls
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server_openfda.client import OpenFDAError, query_openfda
from mcp_server_openfda.faers_codes import (
    DRUG_CHARACTERIZATION,
    PATIENT_AGE_UNIT,
    PATIENT_SEX,
    REACTION_OUTCOME,
    REPORTER_QUALIFICATION,
    format_faers_date,
    normalize_meddra_term,
    translate,
    translate_serious,
)

# The server's MCP name. This is what Claude Desktop displays in its
# MCP servers list and what tool calls are routed against.
mcp = FastMCP("signalbridge-openfda")


# ---------------------------------------------------------------------------
# Tool: ping
# ---------------------------------------------------------------------------

@mcp.tool()
def ping() -> str:
    """Verify the SignalBridge openFDA MCP server is reachable.

    Use this to confirm end-to-end MCP wiring before calling data tools.
    Returns a fixed identification string. Takes no arguments.
    """
    return "SignalBridge openFDA MCP server v0.1.0 - alive."


# ---------------------------------------------------------------------------
# Helpers for search_drug_adverse_events
# ---------------------------------------------------------------------------

def _date_to_openfda(iso_date: str) -> str:
    """Convert ISO YYYY-MM-DD to openFDA's YYYYMMDD format.

    openFDA's `receivedate` field is stored as YYYYMMDD without separators.
    We accept ISO dates from the LLM because that's the universal format,
    then translate at the edge.
    """
    return iso_date.replace("-", "")


def _build_adverse_event_search(
    drug_name: str,
    reaction: str | None,
    start_date: str | None,
    end_date: str | None,
    min_age: int | None,
    max_age: int | None,
    country: str | None,
) -> str:
    """Build the openFDA `search` parameter for /drug/event.json.

    Returns a Lucene-style query string. httpx will URL-encode it on send.
    The drug_name clause searches three normalized openFDA name fields
    (generic, brand, substance) for best PV case capture.
    """
    clauses: list[str] = []

    # Drug name: broad match across generic, brand, and active substance.
    # Quoted so multi-word drug names stay as a single phrase.
    # Note: in the /drug/event endpoint the `openfda` block is nested under
    # patient.drug, so the field paths must include the patient.drug. prefix.
    drug_clause = (
        f'(patient.drug.openfda.generic_name:"{drug_name}" '
        f'OR patient.drug.openfda.brand_name:"{drug_name}" '
        f'OR patient.drug.openfda.substance_name:"{drug_name}")'
    )
    clauses.append(drug_clause)

    # Optional MedDRA Preferred Term filter on reaction.
    if reaction:
        clauses.append(f'patient.reaction.reactionmeddrapt:"{reaction}"')

    # Date range on receivedate. openFDA expects YYYYMMDD, no separators.
    if start_date or end_date:
        start = _date_to_openfda(start_date) if start_date else "20040101"
        end = _date_to_openfda(end_date) if end_date else "21000101"
        clauses.append(f"receivedate:[{start} TO {end}]")

    # Age range on patient.patientonsetage. Note: only catches reports
    # where age is recorded in years (the default unit). Other unit codes
    # would not match this clause.
    if min_age is not None or max_age is not None:
        lo = min_age if min_age is not None else 0
        hi = max_age if max_age is not None else 999
        clauses.append(f"patient.patientonsetage:[{lo} TO {hi}]")

    # Country: FAERS uses 2-letter ISO codes (US, GB, IN, ...).
    if country:
        clauses.append(f"primarysource.reportercountry:{country}")

    return " AND ".join(clauses)


def _tidy_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a FAERS record to the fields a PV reviewer typically wants.

    FAERS records have 50+ fields each. Returning them raw blows out the
    LLM context and makes the response harder to skim. This helper picks
    a PV-relevant subset, applies ICH E2B code translations (sex,
    seriousness, reporter qualification, drug characterization, reaction
    outcome, age unit) via the faers_codes module, and formats dates as
    ISO YYYY-MM-DD.
    """
    patient = raw.get("patient", {}) or {}
    primary_source = raw.get("primarysource", {}) or {}

    drugs = []
    for drug in patient.get("drug", []) or []:
        openfda = drug.get("openfda", {}) or {}
        drugs.append({
            "reported_name": drug.get("medicinalproduct"),
            "generic_name": openfda.get("generic_name"),
            "brand_name": openfda.get("brand_name"),
            "characterization": translate(
                DRUG_CHARACTERIZATION, drug.get("drugcharacterization")
            ),
            "indication": drug.get("drugindication"),
        })

    reactions = []
    for reaction in patient.get("reaction", []) or []:
        reactions.append({
            "term": reaction.get("reactionmeddrapt"),
            "outcome": translate(REACTION_OUTCOME, reaction.get("reactionoutcome")),
        })

    # patientonsetage is sometimes shipped as a numeric string. Coerce to
    # int when it cleanly converts so downstream consumers don't have to
    # re-parse for range comparisons; otherwise pass through as-is.
    raw_age = patient.get("patientonsetage")
    try:
        patient_age: int | str | None = (
            int(raw_age) if raw_age is not None and raw_age != "" else None
        )
    except (TypeError, ValueError):
        patient_age = raw_age

    return {
        "report_id": raw.get("safetyreportid"),
        "received_date": format_faers_date(raw.get("receivedate")),
        "country_of_report": primary_source.get("reportercountry"),
        "reporter_qualification": translate(
            REPORTER_QUALIFICATION, primary_source.get("qualification")
        ),
        "patient_age": patient_age,
        "patient_age_unit": translate(
            PATIENT_AGE_UNIT, patient.get("patientonsetageunit")
        ),
        "patient_sex": translate(PATIENT_SEX, patient.get("patientsex")),
        "serious": translate_serious(raw.get("serious")),
        "patient_died": "patientdeath" in patient,
        "drugs": drugs,
        "reactions": reactions,
    }


async def _top_reactions(
    search_query: str,
    api_key: str | None,
    n: int = 10,
) -> list[dict[str, Any]]:
    """Run a separate openFDA `count` query to get the top reactions.

    openFDA returns counts as {"term": "<MedDRA PT>", "count": N}. The
    .exact aggregation returns terms in storage case (often UPPERCASE),
    while record-level reads return them in MedDRA's native sentence
    case. We normalize at this boundary so the rest of the response —
    top_reactions itself plus the narrowing hint that quotes them —
    uses one consistent convention.
    """
    response = await query_openfda(
        endpoint="/drug/event.json",
        params={
            "search": search_query,
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": n,
        },
        api_key=api_key,
    )
    raw_results = response.get("results", [])
    return [
        {
            "term": normalize_meddra_term(item.get("term")),
            "count": item.get("count"),
        }
        for item in raw_results
    ]


# ---------------------------------------------------------------------------
# Tool: search_drug_adverse_events
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_drug_adverse_events(
    drug_name: str,
    reaction: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    country: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search FAERS adverse-event reports for a drug, with PV-aware filters.

    Searches openFDA's /drug/event endpoint. Drug name matching is broad:
    the search hits the normalized openfda.generic_name, openfda.brand_name,
    and openfda.substance_name fields, so a single name reliably catches
    cases filed under any of the three.

    Important context for the calling LLM:
        - openFDA expects MedDRA terminology for the `reaction` filter.
          Pass a Preferred Term (PT), e.g. "Pneumonitis", "Diarrhoea",
          "Myocardial infarction". Lay terms ("rash", "headache") may
          underperform because FAERS does not store them. v0.2 will add
          MedDRA mapping; for now this is a known limitation.
        - Dates use ISO YYYY-MM-DD. They are mapped to FAERS receivedate.
        - Age range is matched on patient.patientonsetage in years; reports
          where age was recorded in months/days will not match age filters.
        - Country uses 2-letter ISO codes (US, GB, IN, JP, ...).

    Args:
        drug_name: Drug name to search (generic, brand, or substance).
        reaction: Optional MedDRA PT to filter reactions.
        start_date: Optional ISO YYYY-MM-DD lower bound on receivedate.
        end_date: Optional ISO YYYY-MM-DD upper bound on receivedate.
        min_age: Optional minimum patient age (years).
        max_age: Optional maximum patient age (years).
        country: Optional 2-letter ISO country code of the report origin.
        limit: Max records returned in the response (default 100).
            The total matching count is always returned regardless.

    Returns:
        A dict with:
            total_matching: total number of reports matching the filters.
            returned: number of records included in this response.
            records: list of tidied report objects (see _tidy_record).
            top_reactions: list of {term, count} for the most common
                reactions across all matching reports (not just returned).
            narrowing_hint: optional human-readable suggestion when the
                result set is large.
    """
    search_query = _build_adverse_event_search(
        drug_name=drug_name,
        reaction=reaction,
        start_date=start_date,
        end_date=end_date,
        min_age=min_age,
        max_age=max_age,
        country=country,
    )

    # Cap user-supplied limit at openFDA's per-request maximum (1000).
    safe_limit = max(1, min(limit, 1000))

    try:
        page = await query_openfda(
            endpoint="/drug/event.json",
            params={"search": search_query, "limit": safe_limit},
        )
    except OpenFDAError as e:
        return {
            "error": "openFDA query failed",
            "detail": str(e),
            "search_query": search_query,
        }

    total = page.get("meta", {}).get("results", {}).get("total", 0)
    raw_records = page.get("results", [])
    records = [_tidy_record(r) for r in raw_records]

    # Run a separate count query for the top reactions, but only if there
    # are matches. Skipping the count call on empty results saves a round
    # trip and avoids a 404.
    top_reactions: list[dict[str, Any]] = []
    if total > 0:
        try:
            top_reactions = await _top_reactions(search_query, api_key=None)
        except OpenFDAError:
            # Don't fail the whole tool just because the count call failed;
            # the records themselves are useful on their own.
            top_reactions = []

    response: dict[str, Any] = {
        "total_matching": total,
        "returned": len(records),
        "records": records,
        "top_reactions": top_reactions,
    }

    if total > safe_limit:
        top_terms = ", ".join(r["term"] for r in top_reactions[:3] if r.get("term"))
        hint = (
            f"Result set is large ({total} reports, returned {len(records)}). "
        )
        if top_terms:
            hint += (
                f"Consider narrowing by reaction (top terms: {top_terms}) "
                "or by date range or age."
            )
        else:
            hint += "Consider narrowing by date range, age, or country."
        response["narrowing_hint"] = hint

    return response


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server over stdio transport.

    stdio is the transport Claude Desktop uses to talk to local MCP servers:
    Claude Desktop spawns this process, writes JSON-RPC requests to its stdin,
    and reads responses from its stdout.
    """
    mcp.run()


if __name__ == "__main__":
    main()
