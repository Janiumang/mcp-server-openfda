# Open Issues / Deferred Items

Items intentionally NOT addressed in the current session, plus risks to keep visible.

## Deferred to v0.2 (post-v0.1 ship)

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

1. **`search_drug_adverse_events`** — see `NEXT_STEPS.md` for the design.
2. **`count_adverse_events`** — aggregate via openFDA `count` parameter.
3. **`get_drug_label`** — drug label retrieval.
4. **`search_drug_recalls`** — recalls by drug or firm.
5. **README updates** — only after v0.1 ships, only describing what's actually shipped, written in Jani's voice (per the no-overclaiming and no-ghostwriting rules).
6. **Test strategy** — currently zero tests. Plan a minimal test approach before tool 2 so tools 2–4 can be written test-first. Use `engineering:testing-strategy` skill.

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

## No known bugs at end of Session 01

The only running tool (`ping`) returns the expected string. Nothing else is implemented to break.
