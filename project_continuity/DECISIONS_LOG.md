# Decisions Log

Running record of architectural decisions. Reverse chronological — newest at top.

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
