# Decisions Log

Running record of architectural decisions. Reverse chronological — newest at top.

---

## Session 03 — 2026-05-07 (continuation of Session 02)

### D020 — Recall classification surfaced with description, not just code
- **Decision:** `search_drug_recalls` returns `class_description` alongside `classification` ("Class I" + "Most serious - use of product can cause serious health problems or death").
- **Rationale:** Same principle as the FAERS code translations: a portfolio response should be readable without an external reference card. Class I/II/III meanings aren't widely known outside of regulatory work.

### D019 — Recall firm-name match: tokenized for single-word, phrase for multi-word
- **Decision:** "Pfizer" (single word) uses tokenized match — catches "PFIZER INC", "Pfizer Inc", "Pfizer Pharmaceuticals". "Pfizer Inc" (multi-word) uses phrase match.
- **Rationale:** Most users pass the company short name; tokenized match is the natural behavior. Multi-word inputs are the user explicitly being specific, so phrase match is correct there.

### D018 — Recall classification and status validated upfront
- **Decision:** `search_drug_recalls` validates `classification` against ("Class I", "Class II", "Class III") and `status` against ("Ongoing", "Terminated", "Completed", "Pending") before issuing the openFDA query. Returns a clear corrective error with the valid set if the input is wrong.
- **Rationale:** A silent empty result is worse than a clear error. The LLM can self-correct given a list of valid values.

### D017 — Recall tool requires drug_name OR firm
- **Decision:** `search_drug_recalls` makes both `drug_name` and `firm` optional but requires at least one. Validation upfront with a clear error.
- **Rationale:** Both query patterns are PV-legitimate ("recalls for metformin" and "recalls by Pfizer"). README promises both. But "all recalls everywhere" is too broad for v0.1.

### D016 — get_drug_label per-section truncation with inline recovery affordance
- **Decision:** Each label section is truncated to 4,000 characters by default (configurable via `max_section_chars`). Truncated sections include an inline note telling the LLM how to retrieve more via `sections=[<section_name>]`.
- **Rationale:** Pembrolizumab's full label is 234K characters; one call would blow the LLM context window. Inline recovery note is more LLM-friendly than a structured "_truncated: true" flag because the LLM reads natural language directives reliably.

### D015 — get_drug_label returns most recent label by effective_time
- **Decision:** Single label, picked by `sort=effective_time:desc`. `manufacturer_name` exposed in the response so the LLM can see whose label was returned.
- **Rationale:** Per the design question (Q2 in Session 02 NEXT_STEPS), most-recent is the cleanest answer to "what does the label say today?" Manufacturer-aware queries deferred to v0.2.

### D014 — get_drug_label PV-essential section set (10 sections)
- **Decision:** Default returns boxed_warning, adverse_reactions, warnings_and_cautions, contraindications, drug_interactions, indications_and_usage, dosage_and_administration, pregnancy, pediatric_use, geriatric_use. `sections=[...]` parameter allows targeted overrides.
- **Rationale:** PV review workflow needs the safety triad (boxed/warnings/AE), the contraindications + interactions, the basic clinical context (indications + dosage), and the special-population sections. Skipping clinical_pharmacology, mechanism_of_action, clinical_studies, how_supplied — important but not the primary PV view.

### D013 — count_adverse_events: hybrid architecture (general tool + count_reactions shortcut)
- **Decision:** `count_adverse_events(drug_name, pivot, ...)` accepts all six pivots; `count_reactions(...)` is a separate `@mcp.tool()` that wraps it with `pivot="reaction"`.
- **Rationale:** General tool is API-flexible for the LLM; named shortcut tool is more discoverable for the most common PV question. No code duplication — both share `_count_with_pivot`.

### D012b — count_adverse_events: all six pivots in v0.1
- **Decision:** Ship reaction, country, year, reporter_qualification, concomitant_drug, seriousness_subtype all in v0.1. Two of those (year, seriousness_subtype) are multi-call patterns.
- **Rationale:** Maximalist scope per the user's preference for portfolio rigor. Multi-call patterns use `asyncio.gather` so the wall-clock cost stays close to a single round-trip.

### D012a — Year pivot uses concurrent per-year range queries
- **Decision:** openFDA's `count=receivedate.year` doesn't actually aggregate (the syntax works in `search=` but is silently no-op in `count=`). Year pivot is implemented as one count query per year via `asyncio.gather`. Year boundaries: from start_date or 2004 (FAERS public start), to end_date or current calendar year.
- **Rationale:** Detected during smoke test (year pivot returned empty counts on first run). The multi-call pattern is the same shape as seriousness_subtype, so the architecture is consistent.

---

## Session 02 — 2026-05-07

### D012 — Two-call result-size pattern is internal, not exposed
- **Decision:** `search_drug_adverse_events` runs two openFDA calls per invocation: the page query (records + total) and a separate `count=` query (top reactions across the full match set). Both happen inside one tool call; the LLM sees one structured response.
- **Rationale:** Q1's first-N-plus-summary pattern is more useful when the LLM gets the count summary in the same response, not as a separate tool roundtrip. Two HTTP calls per tool invocation is a fair price for that. If the tool gets called heavily and we hit rate limits, revisit.

### D011 — FAERS codes translated to human-readable labels at tool boundary
- **Decision:** `_tidy_record` translates ICH E2B codes (sex, seriousness, drug characterization, reaction outcome, reporter qualification, age unit) into labels via the `faers_codes` module. Dates formatted as ISO YYYY-MM-DD. MedDRA terms in count summaries normalized to sentence case.
- **Rationale:** A FDE-grade portfolio response should be readable without an ICH E2B reference card. PV reviewers can read codes natively; LLMs and most other readers cannot. The faers_codes module also serves as a single source of truth for the remaining three tools.
- **Imperfection acknowledged:** MedDRA proper-noun terms ("Stevens-Johnson syndrome") get partial mis-casing under `.capitalize()`. Tracked for v0.2.

### D010 — Single source-of-truth module for FAERS code translations
- **Decision:** `faers_codes.py` holds all ICH E2B code → label tables and the date/term helpers. Tools import from it; nobody hard-codes a translation in the tool body.
- **Rationale:** Three more tools to come. Consolidating now prevents three more places to update when (e.g.) a new FAERS code value appears.

### D009 — Drug-name search is broad (Q-A → option 1)
- **Decision:** `search_drug_adverse_events` matches across `patient.drug.openfda.generic_name`, `.brand_name`, and `.substance_name`.
- **Rationale:** Best PV case capture. Catches reports filed under brand (Keytruda), generic (pembrolizumab), or substance. Verified during smoke test: pembrolizumab query caught records filed as both KEYTRUDA and PEMBROLIZUMAB.

### D008 — MedDRA reaction filter exposed in v0.1 (Q-B → option 1)
- **Decision:** `search_drug_adverse_events` accepts an optional `reaction: str | None` parameter, documented as expecting a MedDRA Preferred Term.
- **Rationale:** The README's example query (pembrolizumab safety profile) implies users will want to drill into specific reactions. Adding it now is cheap and aligned with PV workflow.
- **Limitation documented in tool description:** lay terms ("rash", "headache") underperform; MedDRA mapping is v0.2.

### D007 — Seriousness filter deferred (Q-C → option 3)
- **Decision:** v0.1 does NOT expose a seriousness filter on `search_drug_adverse_events`. Defer to v0.2 or include in `count_adverse_events`'s pivot list.
- **Rationale:** Tight v0.1 timebox. Smaller initial surface area to test.

---

## Session 01 — 2026-05-06

### D006 — GitHub auth via `gh` CLI
- **Decision:** Use `gh auth login` to manage GitHub HTTPS credentials.
- **Rationale:** Mac had cached creds for a different account from a previous project. `gh` configures a credential helper cleanly and lets us re-auth as Janiumang without manual Keychain surgery or PAT management.
- **Alternative considered:** Manual Keychain edit + Personal Access Token. Rejected — more steps, more breakable.

### D005 — `.DS_Store` ignored repo-wide
- **Decision:** Add `.DS_Store` and `**/.DS_Store` to `.gitignore`. Untrack any committed copies.
- **Rationale:** Public portfolio repo. macOS metadata files are noise and a small filesystem-state leak. The Python `.gitignore` GitHub generated did not cover OS-level artifacts.

### D004 — Author identity set globally
- **Decision:** `git config --global user.name "Umang Jani"`, `user.email "umangjani215@gmail.com"`.
- **Rationale:** Default identity was auto-generated from the Mac's hostname, which doesn't match Jani's GitHub profile. Commits would not link to the GitHub avatar/profile.

### D003 — Python package layout
- **Decision:** `src/` layout with package name `mcp_server_openfda` (matches repo name verbatim).
- **Rationale:** Matches Anthropic reference servers (`mcp-server-fetch`, `mcp-server-filesystem`) — the convention is repo name → package name with hyphens swapped for underscores. SignalBridge brand identity lives in the registered MCP server name and the README, not the Python import path.
- **Alternative considered:** Package name `signalbridge_openfda`. Rejected — diverges from Anthropic conventions for no real gain.

### D002 — Package manager
- **Decision:** `uv` instead of `pip` + `virtualenv`.
- **Rationale:** Anthropic's MCP Python SDK quickstart uses `uv`. Single tool replaces pip + virtualenv + pyenv. Lockfile (`uv.lock`) gives reproducibility. Faster install times.

### D001 — MCP API surface
- **Decision:** `FastMCP` (high-level decorator API) over the lower-level `Server` class.
- **Rationale:** Auto-derives JSON schema from Python type hints + docstrings. Less boilerplate. Matches the official quickstart and most reference servers. Good fit for a v0.1 with four tools.
- **Alternative considered:** Low-level `Server`. Rejected for v0.1 — adds boilerplate for no current benefit. Reconsider only if FastMCP becomes a constraint.

---

## Architectural decisions from session 01 brief (Q1/Q2/Q3)

### Q1 — Result size handling
- **Decision:** Return first N records (default ~100) plus a count-summary metadata block (total count, top reactions, suggested narrowing).
- **Rejected:** (a) Refuse and require narrowing — too restrictive for legitimate broad PV queries. (b) Return all records — blows the LLM context window, slows the call, triggers rate limits.

### Q2 — MedDRA terminology in v0.1
- **Decision:** Pass-through search. Tool descriptions tell the LLM that openFDA expects MedDRA Preferred Terms (PT) and Lowest-Level Terms (LLT). Document the limitation honestly in the README and tool docstrings.
- **Rejected:** (a) Informal synonym dictionary (`headache` → multiple PTs) — risky for PV (false matches matter), would ship a non-validated mapping under the SignalBridge name. (b) Vendoring VigilantAI's MedDRA component — IP/license concerns: VigilantAI is a separate (proprietary) project, and the MedDRA dictionary itself is licensed by ICH/MSSO and not freely redistributable in MIT-licensed open-source.
- **Deferred to v0.2:** Clean MedDRA mapping layer, designed deliberately, with licensing reviewed.

### Q3 — v0.1 scope
- **Decision:** Drug endpoints only. Therapeutic biologics (e.g., pembrolizumab) are already covered because FAERS contains CDER/CBER-regulated biologics. The README's pembrolizumab example holds.
- **Rejected:** (a) Drug + device — doubles surface area, different PV discipline. (b) Drug + device + food — pushes past the 2–3 weekend timebox.
- **Important fact:** Vaccine adverse events live in VAERS (vaers.hhs.gov), NOT openFDA. VAERS is a separate CDC/FDA system with a different schema. Vaccine coverage is deferred to a future separate connector (likely `mcp-server-vaers` under the SignalBridge umbrella) rather than bolted onto this repo.
