"""SignalBridge for openFDA - MCP server entry point.

v0.1 in progress. Currently exposes:
    - ping: trivial wiring check
    - search_drug_adverse_events: FAERS report search with PV-aware filters
    - count_adverse_events: FAERS aggregate counts across PV pivots
    - count_reactions: shortcut for count_adverse_events with pivot='reaction'
    - get_drug_label: most recent FDA drug label, PV-essential sections

Still to come for v0.1:
    - search_drug_recalls
"""

from __future__ import annotations

import asyncio
import datetime
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
# Helpers for count_adverse_events and count_reactions
# ---------------------------------------------------------------------------

# Pivot name (LLM-facing) -> openFDA `count` field. Used for the four
# single-call pivots. year and seriousness_subtype are multi-call and
# handled in dedicated helpers because openFDA's `count=` aggregation
# does not natively bucket by year and does not natively distribute
# across the seriousness flag fields.
_PIVOT_FIELD_MAP: dict[str, str] = {
    "reaction": "patient.reaction.reactionmeddrapt.exact",
    "country": "primarysource.reportercountry.exact",
    "reporter_qualification": "primarysource.qualification",
    "concomitant_drug": "patient.drug.openfda.generic_name.exact",
}

# FAERS public data starts 2004. Used as the lower bound for the year
# pivot when no start_date is supplied.
_FAERS_DATA_START_YEAR = 2004

# The six FAERS seriousness subtype flags (ICH E2B element A.1.5.1.x).
# Each is a {field, label} pair: field is the openFDA flag we count on,
# label is the human-readable subtype name we show in the response.
_SERIOUSNESS_SUBTYPE_FIELDS: list[tuple[str, str]] = [
    ("seriousnessdeath", "Death"),
    ("seriousnesslifethreatening", "Life-threatening"),
    ("seriousnesshospitalization", "Hospitalization"),
    ("seriousnessdisabling", "Disabling"),
    ("seriousnesscongenitalanomali", "Congenital anomaly"),
    ("seriousnessother", "Other medically important"),
]

VALID_PIVOTS: tuple[str, ...] = (
    "reaction",
    "country",
    "year",
    "reporter_qualification",
    "concomitant_drug",
    "seriousness_subtype",
)


def _label_pivot_count(pivot: str, item: dict[str, Any]) -> dict[str, Any]:
    """Convert a single openFDA count-result item into our response shape.

    openFDA returns count results as {"term": <raw>, "count": <n>}. We
    rename to {"label": <human-readable>, "count": <n>} and apply
    pivot-specific normalization:

        - reaction: MedDRA case normalization (sentence case)
        - reporter_qualification: ICH E2B code translation
        - concomitant_drug: title-case (storage form is uppercase)
        - country, year: passed through as strings
    """
    raw_term = item.get("term")
    count = item.get("count", 0)

    if pivot == "reaction":
        label = normalize_meddra_term(raw_term)
    elif pivot == "reporter_qualification":
        translated = translate(REPORTER_QUALIFICATION, raw_term)
        # Surface unknown codes rather than dropping them silently.
        label = translated if translated is not None else f"Code {raw_term}"
    elif pivot == "concomitant_drug":
        label = str(raw_term).title() if raw_term else None
    else:
        # country, year, fallback
        label = str(raw_term) if raw_term not in (None, "") else None

    return {"label": label, "count": count}


async def _count_by_year(
    base_search_query: str,
    start_date: str | None,
    end_date: str | None,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Aggregate report counts per year via concurrent range queries.

    openFDA's `count=` parameter does not natively bucket by year on
    `receivedate`. To answer "how many reports per year?" we issue one
    concurrent query per year in the requested window, each filtering
    receivedate to that year and reading the total from meta.results.

    Year boundaries:
        - If start_date is provided, its year is the lower bound.
          Otherwise we use FAERS's public data start year (2004).
        - If end_date is provided, its year is the upper bound.
          Otherwise we use the current calendar year.
        - If start > end, returns empty.

    Returns counts in chronological order so the response reads as a
    trend timeline. Zero-count years are kept (intentionally) — they
    are PV-meaningful (e.g. drug pre-approval, reporting gap).
    """
    try:
        start_year = int(start_date[:4]) if start_date else _FAERS_DATA_START_YEAR
    except (TypeError, ValueError):
        start_year = _FAERS_DATA_START_YEAR

    try:
        end_year = (
            int(end_date[:4])
            if end_date
            else datetime.datetime.now(datetime.timezone.utc).year
        )
    except (TypeError, ValueError):
        end_year = datetime.datetime.now(datetime.timezone.utc).year

    if end_year < start_year:
        return []

    async def count_one_year(year: int) -> dict[str, Any]:
        year_query = (
            f"({base_search_query}) AND "
            f"receivedate:[{year}0101 TO {year}1231]"
        )
        try:
            response = await query_openfda(
                endpoint="/drug/event.json",
                params={"search": year_query, "limit": 1},
                api_key=api_key,
            )
        except OpenFDAError:
            return {"label": str(year), "count": None}
        total = response.get("meta", {}).get("results", {}).get("total", 0)
        return {"label": str(year), "count": total}

    tasks = [count_one_year(year) for year in range(start_year, end_year + 1)]
    results = await asyncio.gather(*tasks)
    # Already in chronological order (range generates ascending years).
    return list(results)


async def _count_seriousness_subtypes(
    search_query: str,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Aggregate the six FAERS seriousness subtype flags concurrently.

    Each FAERS seriousness subtype is a 1/null flag stored on its own
    field. To answer "how many of these reports were each kind of
    serious?" we issue six independent count queries (one per flag),
    extract the count of records where the flag is set to "1", and
    return them merged into one ordered list.

    Concurrency via asyncio.gather brings the wall-clock cost back down
    to a single round-trip's worth — the queries don't block each other.
    """
    async def count_one(field: str, label: str) -> dict[str, Any]:
        try:
            response = await query_openfda(
                endpoint="/drug/event.json",
                params={
                    "search": search_query,
                    "count": field,
                    "limit": 5,
                },
                api_key=api_key,
            )
        except OpenFDAError:
            # Don't blow up the whole pivot if one subtype call fails;
            # surface the absence with count=None so the LLM can see
            # the gap rather than mistake it for a true zero.
            return {"label": label, "count": None}

        # The "1" bucket is set-true; "2"/null is set-false. We only
        # report the count of set-true. Some FAERS records omit the
        # flag entirely (not 1 or 2), which is treated as not-serious.
        for entry in response.get("results", []):
            if str(entry.get("term")) == "1":
                return {"label": label, "count": entry.get("count", 0)}
        return {"label": label, "count": 0}

    tasks = [count_one(field, label) for field, label in _SERIOUSNESS_SUBTYPE_FIELDS]
    results = await asyncio.gather(*tasks)
    return list(results)


async def _count_with_pivot(
    drug_name: str,
    pivot: str,
    reaction: str | None,
    start_date: str | None,
    end_date: str | None,
    min_age: int | None,
    max_age: int | None,
    country: str | None,
    limit: int,
) -> dict[str, Any]:
    """Shared implementation for count_adverse_events and count_reactions.

    Builds the same search query as `search_drug_adverse_events` so the
    filter semantics are identical across the two tools. Dispatches on
    the requested pivot to either a single-call openFDA count query or
    the multi-call seriousness_subtype handler.
    """
    if pivot not in VALID_PIVOTS:
        return {
            "error": f"Unknown pivot: {pivot!r}",
            "valid_pivots": list(VALID_PIVOTS),
        }

    search_query = _build_adverse_event_search(
        drug_name=drug_name,
        reaction=reaction,
        start_date=start_date,
        end_date=end_date,
        min_age=min_age,
        max_age=max_age,
        country=country,
    )

    # Step 1: get the total. This anchors the counts ("X out of Y") and
    # also tells us when the filter set is empty so we can short-circuit.
    try:
        meta_response = await query_openfda(
            endpoint="/drug/event.json",
            params={"search": search_query, "limit": 1},
        )
    except OpenFDAError as e:
        return {
            "error": "openFDA filter query failed",
            "detail": str(e),
            "search_query": search_query,
        }

    total = meta_response.get("meta", {}).get("results", {}).get("total", 0)

    if total == 0:
        return {
            "drug_name": drug_name,
            "pivot": pivot,
            "total_matching": 0,
            "counts": [],
        }

    # Step 2: get the pivot counts.
    if pivot == "seriousness_subtype":
        counts = await _count_seriousness_subtypes(search_query, api_key=None)
        # Order by count descending (most-frequent subtype first).
        counts = sorted(
            counts,
            key=lambda c: (c.get("count") or 0),
            reverse=True,
        )
    elif pivot == "year":
        # Multi-call: one count query per year in the window.
        counts = await _count_by_year(
            search_query,
            start_date=start_date,
            end_date=end_date,
            api_key=None,
        )
    else:
        try:
            count_response = await query_openfda(
                endpoint="/drug/event.json",
                params={
                    "search": search_query,
                    "count": _PIVOT_FIELD_MAP[pivot],
                    "limit": max(1, min(limit, 100)),
                },
            )
        except OpenFDAError as e:
            return {
                "error": "openFDA count query failed",
                "detail": str(e),
                "pivot": pivot,
                "search_query": search_query,
            }

        raw_results = count_response.get("results", [])
        counts = [_label_pivot_count(pivot, item) for item in raw_results]

        # concomitant_drug: filter out the search drug itself, since it
        # appears in every matching record by definition.
        if pivot == "concomitant_drug":
            target = drug_name.strip().upper()
            counts = [
                c for c in counts
                if (c.get("label") or "").upper() != target
            ]

    response: dict[str, Any] = {
        "drug_name": drug_name,
        "pivot": pivot,
        "total_matching": total,
        "counts": counts,
    }

    # Narrowing hint: only relevant for unbounded-cardinality pivots.
    # seriousness_subtype is exactly six fixed buckets; year is small
    # by definition; the others can be wide.
    if pivot in ("reaction", "country", "reporter_qualification", "concomitant_drug"):
        if len(counts) >= max(1, min(limit, 100)):
            response["narrowing_hint"] = (
                f"Returned the top {len(counts)} {pivot} values out of "
                f"{total} matching reports. Add filters (date range, "
                "reaction, country, age) to narrow the match set."
            )

    return response


# ---------------------------------------------------------------------------
# Tool: count_adverse_events
# ---------------------------------------------------------------------------

@mcp.tool()
async def count_adverse_events(
    drug_name: str,
    pivot: str = "reaction",
    reaction: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    country: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Aggregate FAERS adverse-event counts across a chosen pivot dimension.

    Same filter semantics as search_drug_adverse_events (broad drug-name
    match across generic/brand/substance, optional MedDRA reaction filter,
    ISO date range, age range, country). Returns the count of matching
    records grouped by the requested pivot.

    Supported pivots:
        - "reaction" (default): MedDRA Preferred Term distribution.
          Same data as the count summary in search_drug_adverse_events,
          but exposed as its own tool for explicit aggregate queries.
        - "country": Reports grouped by primarysource.reportercountry.
          Useful for geographic distribution questions.
        - "year": Reports grouped by year of receivedate. Returned in
          chronological order for trend analysis.
        - "reporter_qualification": Reports grouped by who filed them
          (Physician, Pharmacist, Consumer, etc.) using the ICH E2B
          qualification codes, translated to labels.
        - "concomitant_drug": Other drugs co-reported in the same
          records. The search drug itself is filtered out of the result
          (every matching record has it by definition). Caveat: openFDA
          does not natively distinguish suspect vs. concomitant drugs
          in the count query, so the result includes drugs the report
          characterized as suspect alongside true concomitants.
        - "seriousness_subtype": Counts across the six FAERS seriousness
          flags (Death, Life-threatening, Hospitalization, Disabling,
          Congenital anomaly, Other medically important). Returns the
          number of reports flagged for each subtype, sorted descending.

    Args:
        drug_name: Drug name to search (matched broadly across generic,
            brand, and substance — same as search_drug_adverse_events).
        pivot: One of "reaction", "country", "year",
            "reporter_qualification", "concomitant_drug", or
            "seriousness_subtype". Defaults to "reaction".
        reaction: Optional MedDRA Preferred Term filter (applies BEFORE
            the pivot is computed).
        start_date: Optional ISO YYYY-MM-DD lower bound on receivedate.
        end_date: Optional ISO YYYY-MM-DD upper bound on receivedate.
        min_age: Optional minimum patient age in years.
        max_age: Optional maximum patient age in years.
        country: Optional 2-letter ISO country filter.
        limit: Maximum number of distinct pivot values returned for
            single-call pivots (ignored for seriousness_subtype, which
            always returns six). Default 25, max 100.

    Returns:
        A dict with:
            drug_name: echo of the input.
            pivot: which pivot was used.
            total_matching: total reports matching the filter set.
            counts: list of {label, count} pairs.
            narrowing_hint: optional, when the pivot returned its full
                limit (suggesting more values exist).
    """
    return await _count_with_pivot(
        drug_name=drug_name,
        pivot=pivot,
        reaction=reaction,
        start_date=start_date,
        end_date=end_date,
        min_age=min_age,
        max_age=max_age,
        country=country,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Tool: count_reactions (shortcut for the most common pivot)
# ---------------------------------------------------------------------------

@mcp.tool()
async def count_reactions(
    drug_name: str,
    reaction: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    country: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Top MedDRA Preferred Terms reported with a drug.

    Convenience tool. Equivalent to count_adverse_events(
    drug_name, pivot="reaction", ...) but exposed as its own tool so the
    LLM can find it by name for the most common PV question:
    "what reactions are reported with this drug?"

    Same filter semantics and response shape as count_adverse_events
    with pivot="reaction". See that tool's documentation for arg detail.

    Args:
        drug_name: Drug name to search (broad match across generic,
            brand, and substance).
        reaction: Optional MedDRA PT filter applied before counting
            (useful for narrowing to a clinical area).
        start_date, end_date: ISO YYYY-MM-DD bounds on receivedate.
        min_age, max_age: Patient age range in years.
        country: 2-letter ISO country code filter.
        limit: Top N reactions returned (default 25, max 100).

    Returns:
        Same shape as count_adverse_events with pivot="reaction".
    """
    return await _count_with_pivot(
        drug_name=drug_name,
        pivot="reaction",
        reaction=reaction,
        start_date=start_date,
        end_date=end_date,
        min_age=min_age,
        max_age=max_age,
        country=country,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Helpers for get_drug_label
# ---------------------------------------------------------------------------

# The PV-essential subset of /drug/label.json sections. Returned even if
# absent from the specific label (as null) so the LLM can distinguish
# "no boxed warning exists for this drug" from "we forgot to look."
_LABEL_PV_SECTIONS: tuple[str, ...] = (
    "boxed_warning",
    "adverse_reactions",
    "warnings_and_cautions",
    "contraindications",
    "drug_interactions",
    "indications_and_usage",
    "dosage_and_administration",
    "pregnancy",
    "pediatric_use",
    "geriatric_use",
)


def _build_label_search(drug_name: str) -> str:
    """Build a /drug/label.json `search` query for broad drug-name match.

    Important schema note: in the label endpoint the `openfda` enrichment
    block is at the TOP level of each label document, NOT nested under
    `patient.drug` as in the event endpoint. This is the same schema
    surprise that bit us during tool 1's first smoke test - same broad
    name pattern, different field paths.
    """
    return (
        f'openfda.generic_name:"{drug_name}" '
        f'OR openfda.brand_name:"{drug_name}" '
        f'OR openfda.substance_name:"{drug_name}"'
    )


def _section_text(section_value: Any) -> str | None:
    """Render an openFDA label section value into a single string.

    openFDA returns each label section as a list of strings, one entry
    per XML chunk in the underlying SPL document. We join them with two
    newlines so the LLM sees one readable block per section. Returns
    None when the section is absent or empty - meaningful PV signal
    (e.g., a drug with no boxed warning).
    """
    if section_value is None:
        return None
    if isinstance(section_value, list):
        non_empty = [s.strip() for s in section_value if isinstance(s, str) and s.strip()]
        if not non_empty:
            return None
        return "\n\n".join(non_empty)
    if isinstance(section_value, str):
        s = section_value.strip()
        return s if s else None
    return str(section_value)


# ---------------------------------------------------------------------------
# Tool: get_drug_label
# ---------------------------------------------------------------------------

def _truncate_section(text: str | None, limit: int, section_name: str) -> str | None:
    """Cap a section's text at `limit` characters, appending a recovery note.

    Keeping the recovery note inline (rather than a structured flag) lets
    the LLM read the truncation in plain language and decide whether to
    re-call with sections=[<this>] for the full text. Sections under the
    limit pass through unchanged.
    """
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n\n[Section truncated: showing first {limit:,} of {len(text):,} "
        f"characters. Re-call get_drug_label with sections=['{section_name}'] "
        "and a larger max_section_chars to retrieve more of this section.]"
    )


@mcp.tool()
async def get_drug_label(
    drug_name: str,
    sections: list[str] | None = None,
    max_section_chars: int = 4000,
) -> dict[str, Any]:
    """Return the most recent FDA drug label for a drug, PV sections only.

    Looks up the drug in openFDA's /drug/label.json endpoint with broad
    name matching across generic, brand, and active substance, then
    returns the most recently effective label. "Most recent" is decided
    by openFDA's effective_time field, sorted descending.

    By default returns ten PV-essential sections (when present):
        - boxed_warning
        - adverse_reactions
        - warnings_and_cautions
        - contraindications
        - drug_interactions
        - indications_and_usage
        - dosage_and_administration
        - pregnancy
        - pediatric_use
        - geriatric_use

    Sections absent from the specific label come back as null rather than
    being omitted, so the LLM (and the human reader) can distinguish
    "this drug has no boxed warning" from "we forgot to look at that
    section." That distinction is meaningful in pharmacovigilance.

    Long sections are truncated. Adverse-reactions sections for cancer
    drugs and complex biologics regularly run 100,000+ characters, which
    blows the LLM context window and is rarely useful in one bite. The
    default per-section cap is 4,000 characters (~1,000 tokens). When a
    section is truncated, the response text ends with an explicit note
    telling the LLM how to re-retrieve more of that section using the
    `sections` parameter.

    Important context for the calling LLM:
        - Most recently revised label may not be the brand-name innovator
          label; it could be a generic manufacturer's most recent
          submission. v0.2 will add an optional manufacturer filter.
        - Each section is a single rendered string (multiple SPL XML
          chunks joined with two newlines).
        - To see the full text of a long section, re-call with
          sections=["adverse_reactions"] (or whichever) plus a larger
          max_section_chars (e.g., 50000).

    Args:
        drug_name: Drug name to look up. Matched broadly across generic,
            brand, and substance fields.
        sections: Optional list of section names to return. When omitted,
            all ten PV-essential sections are returned. Useful for
            zooming into a specific section after seeing it truncated.
        max_section_chars: Per-section character cap. Default 4000.
            Sections shorter than the cap pass through unchanged.

    Returns:
        Dict with:
            drug_name_query: echo of the input.
            label_metadata: {generic_name, brand_name, substance_name,
                manufacturer_name, application_number, effective_time}.
                Each value is a list (openFDA's native shape) or null.
                effective_time is reformatted to ISO YYYY-MM-DD.
            sections: dict mapping each requested section name to its
                rendered string, or null if the section is absent. Long
                sections are truncated with an inline recovery note.
        Or, on no-match: {"drug_name_query": ..., "error": "No FDA label
        found matching this drug name"}.
    """
    target_sections = list(sections) if sections else list(_LABEL_PV_SECTIONS)
    invalid = [s for s in target_sections if s not in _LABEL_PV_SECTIONS]
    if invalid:
        return {
            "drug_name_query": drug_name,
            "error": f"Unknown section name(s): {invalid}.",
            "valid_sections": list(_LABEL_PV_SECTIONS),
        }

    safe_max_chars = max(500, max_section_chars)

    search_query = _build_label_search(drug_name)

    try:
        response = await query_openfda(
            endpoint="/drug/label.json",
            params={
                "search": search_query,
                "sort": "effective_time:desc",
                "limit": 1,
            },
        )
    except OpenFDAError as e:
        return {
            "error": "openFDA label query failed",
            "detail": str(e),
            "drug_name_query": drug_name,
        }

    results = response.get("results", [])
    if not results:
        return {
            "drug_name_query": drug_name,
            "error": "No FDA label found matching this drug name.",
        }

    label = results[0]
    openfda = label.get("openfda", {}) or {}

    metadata = {
        "generic_name": openfda.get("generic_name"),
        "brand_name": openfda.get("brand_name"),
        "substance_name": openfda.get("substance_name"),
        "manufacturer_name": openfda.get("manufacturer_name"),
        "application_number": openfda.get("application_number"),
        "effective_time": format_faers_date(label.get("effective_time")),
    }

    sections_out = {
        section: _truncate_section(
            _section_text(label.get(section)),
            safe_max_chars,
            section,
        )
        for section in target_sections
    }

    return {
        "drug_name_query": drug_name,
        "label_metadata": metadata,
        "sections": sections_out,
    }


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
