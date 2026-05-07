# NEXT SESSION — START HERE

**Resume point:** Build the first real openFDA tool, `search_drug_adverse_events`.

## Status going in

- v0.1 scaffolding complete and pushed to GitHub.
- One trivial tool (`ping`) is live and verified end-to-end through Claude Desktop.
- Four real tools remaining for v0.1.
- No tests yet.

## Most likely next 3 actions

### 1. Sketch the input schema for `search_drug_adverse_events`

Decide which openFDA `/drug/event` query parameters to expose to the LLM. Recommended starting set:

- `drug_name` (string) — searches `patient.drug.medicinalproduct` OR `openfda.generic_name` OR `openfda.brand_name`. Decide which during design.
- `start_date` / `end_date` (ISO YYYY-MM-DD strings) — maps to `receivedate`.
- `min_age` / `max_age` (int) — maps to `patient.patientonsetage`.
- `country` (optional, ISO country code) — maps to `primarysource.reportercountry`.
- `limit` (int, default 100) — applies the result-size pattern from Q1.

Open design questions:
- Reaction filter (MedDRA PT)? Per Q2 decision, expose as a string parameter `reaction` and document in tool description that openFDA expects MedDRA Preferred Terms. No translation in v0.1.
- Serious-only toggle? FAERS field `serious` — useful PV signal but adds surface area. Defer unless trivial.

### 2. Build the openFDA HTTP client

Create `src/mcp_server_openfda/client.py`. Make `httpx` an explicit dependency (currently transitive). Single async function:

```python
async def query_openfda(
    endpoint: str,        # e.g. "/drug/event.json"
    params: dict,         # query params (excluding api_key)
    api_key: str | None,  # from OPENFDA_API_KEY env var
) -> dict:
    ...
```

Behaviors required:
- Read `OPENFDA_API_KEY` from env if `api_key` is None.
- Inject `api_key` into the query string when present.
- Treat HTTP 404 as "no results" — return `{"meta": {"results": {"total": 0}}, "results": []}` rather than raising.
- Other HTTP errors (4xx, 5xx, network) raise so the tool layer can format an LLM-friendly error.
- Use `httpx.AsyncClient` with a sane timeout (e.g. 30s).

### 3. Wire the tool into `server.py`

```python
@mcp.tool()
async def search_drug_adverse_events(...) -> dict:
    """..."""
    raw = await query_openfda("/drug/event.json", params, api_key)
    return summarize(raw, requested_limit)
```

The `summarize` step is the result-size pattern (Q1):
- Total count (from `meta.results.total`).
- First N records (default 100).
- Top reactions count summary (run a separate count query for the same filters).
- "Suggested narrowing" hints if the result set is large.

Test with a real query before declaring done. Suggested smoke test: `pembrolizumab` over the last 5 years, age 65+. README's example query.

## Files/modules involved

- `src/mcp_server_openfda/server.py` — add `search_drug_adverse_events` tool
- `src/mcp_server_openfda/client.py` — new file, HTTP client
- `pyproject.toml` — add `httpx` as explicit dependency (`uv add httpx`)
- `src/mcp_server_openfda/summarize.py` — optional new file for the result-size pattern, or inline in server.py for v0.1

## Dependencies/context required to continue

- openFDA `/drug/event` API docs: https://open.fda.gov/apis/drug/event/
- FAERS field reference for the four tools we care about
- MedDRA terminology note — v0.1 says pass-through, document the limitation in the tool docstring (per Q2)
- `OPENFDA_API_KEY` — optional. Server should work without it but with the lower 240 req/min limit. README should explain how to set it.

## Skills to invoke when resuming

- `engineering:testing-strategy` when planning the first test file
- `engineering:code-review` after the first real tool is implemented
- `regulatory-compliance-quality-guardrail-skill` when finalizing the v0.1 README claims (so the README only describes what's shipped)

## Open questions to revisit at session start

- Should `search_drug_adverse_events` be one tool with many optional filters, or two tools (one minimal, one advanced)? Defer unless the v0.1 surface area gets unwieldy.
- Does the result-size summary block belong in the tool's own response, or is it a separate `count_adverse_events` call? Per Q1 decision, embed in the search tool's response so the LLM gets the count for free.
