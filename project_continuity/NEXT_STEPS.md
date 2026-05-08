# NEXT SESSION — START HERE

**Resume point:** Build `count_adverse_events`, the second of four v0.1 tools.

## Status going in

- Tool 1 (`search_drug_adverse_events`) is shipped at commit `923179c`, end-to-end verified against pembrolizumab.
- The HTTP client (`client.py`) and code translations (`faers_codes.py`) are reusable infrastructure for the remaining three tools.
- Two more tools after this one: `get_drug_label` and `search_drug_recalls`.

## Most likely next 3 actions

### 1. Settle the input schema for `count_adverse_events`

Decide what dimensions to aggregate over. openFDA's `count=<field>.exact` parameter takes one field per call and returns a list of `{term, count}`. Recommended starter set of pivot dimensions:

| LLM-friendly name | openFDA field |
|---|---|
| `reaction` | `patient.reaction.reactionmeddrapt.exact` |
| `country` | `primarysource.reportercountry.exact` |
| `reporter_qualification` | `primarysource.qualification` |
| `seriousness_subtype` | `seriousnessdeath.exact`, `seriousnesshospitalization.exact`, etc. (multiple fields, may need a different shape) |
| `report_year` | `receivedate.year` (openFDA supports date partials) |
| `concomitant_drug` | `patient.drug.openfda.generic_name.exact` (filtered to non-suspect characterization — tricky) |

Decision needed: a single tool with a `pivot` parameter, OR multiple narrow tools (`count_reactions`, `count_by_country`, ...). The README example implies count_adverse_events is one tool with multiple dimensions; I lean toward that path for v0.1.

### 2. Decide the response shape

For each pivot, what does the tool return?
- `total_matching` (same as search tool)
- `pivot_field` (which dimension was aggregated)
- `counts: [{label, count}]` (top N, with code translations applied via faers_codes when applicable, e.g. for reporter_qualification)
- `narrowing_hint` (if applicable)

Reuse `_build_adverse_event_search` from `server.py` for the filter clauses — same drug_name/dates/age/country/reaction parameters as tool 1.

### 3. Implement and smoke-test

Sample query: `count_adverse_events(drug_name="pembrolizumab", pivot="reaction", min_age=65, start_date="2021-05-07", end_date="2026-05-07")` should return roughly the same top reactions our search tool's count summary returned (Malignant neoplasm progression: 2619, etc.) — that's the cross-check.

A second smoke test with `pivot="country"` to verify multi-pivot routing works.

## Files/modules involved

- `src/mcp_server_openfda/server.py` — add new `@mcp.tool()` for `count_adverse_events`. Reuse `_build_adverse_event_search`. Likely add a small `_PIVOT_FIELDS` mapping near the new tool.
- `src/mcp_server_openfda/faers_codes.py` — add a translation for whichever pivot fields require it (e.g. reporter qualification codes are already there; seriousness subtypes need labels).
- `pyproject.toml` — no changes expected.
- `project_continuity/` — update at end of session.

## Open design questions to resolve at session start

1. **One tool with `pivot` vs. multiple narrow tools.** Single tool is more PV-flexible; multiple is more LLM-discoverable. Decide first.
2. **Seriousness subtype shape.** FAERS has six independent subtype fields (death, life-threatening, hospitalization, disabling, congenital anomaly, other). Counting by `seriousness_subtype` either means six separate count queries or a different aggregate shape. Defer if too messy.
3. **Date partials.** openFDA supports `count=receivedate.year` for year-bucket counts. Useful for trend analysis. Decide whether to support `pivot="year"` in v0.1.

## Skills to invoke when resuming

- `engineering:testing-strategy` — by tool 2 we should have a sketch of how we'll test these tools, even if formal test code waits until after tool 4.
- `engineering:code-review` — once tool 2 is in, review tools 1 + 2 together to catch any pattern divergence before tools 3/4 inherit it.
