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

1. ~~`search_drug_adverse_events`~~ — DONE in Session 02 (commit `923179c`, smoke-tested).
2. **`count_adverse_events`** — aggregate via openFDA `count` parameter. Next session start point.
3. **`get_drug_label`** — drug label retrieval.
4. **`search_drug_recalls`** — recalls by drug or firm.
5. **`pyproject.toml` `description` field** — currently still uv's placeholder ("Add your description here"). Polish before v0.1 tag.
6. **README updates** — only after all four tools ship. Describe only what's shipped. Jani writes prose; Claude can suggest structure.
7. **Test strategy** — still zero tests. Use `engineering:testing-strategy` skill before tool 3 at the latest, so we have a pattern in place before tools 3 and 4 inherit untested conventions.

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

## No known bugs at end of Session 02

`ping` and `search_drug_adverse_events` both return correct shapes against live openFDA queries. The bug found mid-session (missing `patient.drug.` prefix on the openfda field paths) was fixed before commit. No other behavior issues identified.
