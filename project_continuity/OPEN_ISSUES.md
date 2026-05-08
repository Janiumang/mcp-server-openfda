# Open Issues / Deferred Items

Items intentionally NOT addressed in the current session, plus risks to keep visible.

## Deferred to v0.2 (post-v0.1 ship)

### MedDRA proper-noun term casing
- `normalize_meddra_term` uses `.capitalize()`, which mis-cases proper-noun PTs (e.g. "Stevens-Johnson syndrome" becomes "Stevens-johnson syndrome").
- Tracked in `faers_codes.py` docstring. Fix likely needs a curated list of MedDRA proper nouns or a different normalization library.

### FAERS within-record duplicates
- Some FAERS reports list the same drug multiple times (Session 02 smoke test: report 19231401 had LENVATINIB MESYLATE listed five times). This is upstream data quality; we pass it through.
- v0.2 candidate: deduplicate by (reported_name, generic_name, characterization) before returning.

### MedDRA terminology mapping
- v0.1 ships pass-through search + a documented limitation.
- v0.2 work: design a clean MedDRA mapping layer.
- **License/IP gate:** Before any code is reused or vendored from VigilantAI, do a deliberate license review. Default assumption: rebuild, do not vendor. The MedDRA dictionary itself is licensed by ICH/MSSO and is not freely redistributable in an MIT repo.

### VAERS / vaccines
- Vaccine adverse events are NOT in openFDA — they live in VAERS (vaers.hhs.gov), a separate CDC/FDA system.
- Plan: separate connector (`mcp-server-vaers`) under the SignalBridge brand, not bolted onto this repo.

### Device + food endpoints
- v0.1 is drug-only.
- Future scope: same-repo expansion vs. separate connectors. Decide per data-shape similarity.

### Label listedness checks, NDC lookup, drug-event co-occurrence detection, PV safety-brief generation
- Explicitly out of scope for v0.1 per the original brief.
- Worth revisiting after v0.1 ships.

## v0.1 work still pending (in priority order)

1. ~~`search_drug_adverse_events`~~ — DONE in Session 02 (commit `923179c`).
2. ~~`count_adverse_events`~~ — DONE in Session 03 (commit `e1aee17`).
3. ~~`count_reactions`~~ — DONE in Session 03 (commit `e1aee17`, hybrid architecture).
4. ~~`get_drug_label`~~ — DONE in Session 03 (commit `b46bae9`).
5. ~~`search_drug_recalls`~~ — DONE in Session 03 (commit `c04b411`). v0.1 feature-complete.
6. ~~`pyproject.toml` description~~ — DONE end of Session 03.
7. **README pass** — Jani writes prose. Claude critiques only. See NEXT_STEPS.md for the suggested structure.
8. **(Optional) v0.1.0 tag** — `git tag -a v0.1.0 -m "..." && git push --tags` once README lands.
9. **Test strategy** — still zero tests. Defer to v0.2 explicitly. Use `engineering:testing-strategy` skill at the start of v0.2 work.

## Risks to track

### Cross-machine reproducibility unverified
- The repo has only been built on Jani's macOS Apple Silicon. `uv sync` on Linux/Windows is untested. Worth a one-time check before any v0.1 announcement.

### openFDA rate limit (240 req/min without API key)
- v0.1 won't include retry-with-backoff. If the server hits HTTP 429, the LLM sees the raw error.
- Mitigation: README should explain `OPENFDA_API_KEY` clearly so power users get the higher limit.
- v0.2 candidate: add backoff + retry to the client.

### Wife's-account credential interference
- Credential issue from this Mac happened once during this session (push initially failed as `thakkerdevanshi93`). Resolved via `gh auth login`.
- If working from a different repo on this same Mac in the future, the credential helper may switch back. Always verify with `gh auth status` and `git config --global --list | grep user` before pushing to this repo.

### MCP SDK version drift
- `mcp[cli]>=1.27.0` — pinned via floor only. `uv.lock` pins the exact installed version.
- If the SDK ships breaking changes in a minor version, `uv lock --upgrade` could pull a version that breaks our server. Defense: don't run `uv lock --upgrade` without intent.

## No known bugs at end of Session 03

All six tools (ping, search_drug_adverse_events, count_adverse_events, count_reactions, get_drug_label, search_drug_recalls) return correct shapes against live openFDA queries. Three mid-session bugs were caught by the smoke-test pattern and fixed before commit:

1. Session 02: missing `patient.drug.` prefix on openfda field paths in `_build_adverse_event_search` (caught in pembrolizumab search returning 0 results).
2. Session 03: count_adverse_events year pivot returning empty counts because `count=receivedate.year` is silently no-op in openFDA — fixed via concurrent per-year range queries.
3. Session 03: get_drug_label response too large for context (234K chars on pembrolizumab) — fixed via per-section truncation + targeted-section retrieval parameter.

## Deferred to v0.2 (post-v0.1 ship), updated for Session 03

In addition to the items already listed above:

### Manufacturer-aware label queries
- `get_drug_label` currently returns the most recent label by effective_time regardless of manufacturer (innovator vs generic). Adding an optional `manufacturer` filter would let PV reviewers see the innovator label specifically when generics exist. Not blocking for v0.1 — the brief says PV reviewers know how to handle this — but a near-term v0.2 polish.

### Rate-limit handling
- v0.1 has no retry-with-backoff. HTTP 429 is surfaced raw. Mitigation today is `OPENFDA_API_KEY` (raises limit to ~120K req/day). v0.2 candidate: exponential backoff on 429 in `client.py`.

### Recall firm matching is brittle for fuzzy names
- Single-word firm input uses tokenized match; multi-word uses phrase match. Doesn't handle typo'd or partial-multiword inputs ("Pfizer Pharma" misses "Pfizer Pharmaceuticals"). v0.2 candidate: switch to wildcard or fuzzy matching.
