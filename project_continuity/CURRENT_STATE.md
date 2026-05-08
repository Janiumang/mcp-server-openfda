# Current State Snapshot

**Last updated:** end of Session 03 (2026-05-07) — v0.1 feature-complete
**Latest commit on `main`:** `c04b411` — feat: add search_drug_recalls tool - v0.1 feature-complete

## Repo layout

```
mcp-server-openfda/
├── .gitignore                       # Python defaults + .DS_Store
├── .python-version                  # 3.11
├── LICENSE                          # MIT
├── README.md                        # Public description (untouched so far)
├── pyproject.toml                   # Project metadata + dependencies
├── uv.lock                          # Locked dep versions (committed)
├── .venv/                           # Local virtual env (gitignored)
├── src/
│   └── mcp_server_openfda/
│       ├── __init__.py              # Re-exports main
│       ├── server.py                # FastMCP server + 6 tools + tool helpers
│       ├── client.py                # openFDA HTTP client (async query_openfda)
│       └── faers_codes.py           # ICH E2B code translations + helpers
└── project_continuity/              # Working notes (this folder)
    ├── SESSION_01_SUMMARY.md
    ├── SESSION_02_SUMMARY.md
    ├── SESSION_03_SUMMARY.md
    ├── CURRENT_STATE.md
    ├── NEXT_STEPS.md
    ├── DECISIONS_LOG.md
    └── OPEN_ISSUES.md
```

## Dependencies

Direct: `mcp[cli]>=1.27.0`, `httpx>=0.28.1`.
Transitive (via mcp/httpx): pydantic, starlette, anyio, click, typer, rich, jsonschema, sse-starlette, uvicorn, python-dotenv, python-multipart, pyjwt, cryptography, etc. — see `uv.lock` for the full pinned list.

## MCP server identity

- **Server name (Claude Desktop):** `signalbridge-openfda`
- **Python package:** `mcp_server_openfda`
- **Console script:** `mcp-server-openfda` (defined in `pyproject.toml [project.scripts]`)
- **Entry point:** `mcp_server_openfda:main` → `mcp.run()` → stdio JSON-RPC loop

## Tools currently exposed (v0.1 feature-complete)

| Tool name | Purpose | Status |
|-----------|---------|--------|
| `ping` | Verify MCP wiring, return a fixed string | Live |
| `search_drug_adverse_events` | FAERS report search (drug, reaction, dates, age, country) with first-N + count summary + narrowing hint | Live, smoke-tested |
| `count_adverse_events` | FAERS aggregate counts across six pivots: reaction, country, year, reporter_qualification, concomitant_drug, seriousness_subtype | Live, smoke-tested |
| `count_reactions` | Shortcut for count_adverse_events with pivot='reaction' | Live, smoke-tested |
| `get_drug_label` | Most recent FDA drug label, 10 PV-essential sections, with per-section truncation + targeted re-retrieval | Live, smoke-tested |
| `search_drug_recalls` | FDA recalls (Form 3500A enforcement) by drug or firm, with classification/status/date filters | Live, smoke-tested |

## Tools planned for v0.1

All four real tools shipped. v0.1 is feature-complete pending the README pass (Jani writes prose) and an optional v0.1.0 tag.

## Build/run commands

| Action | Command |
|--------|---------|
| Sync env from lockfile | `uv sync` |
| Run server manually | `uv run mcp-server-openfda` |
| Run via Claude Desktop | Spawned automatically per `claude_desktop_config.json` |
| Add a dependency | `uv add <package>` |
| Update locked versions | `uv lock --upgrade` |

## Claude Desktop config (relevant excerpt)

```json
{
  "mcpServers": {
    "signalbridge-openfda": {
      "command": "/Users/umang/.local/bin/uv",
      "args": [
        "--directory",
        "/Users/umang/Desktop/Jani Family Projects/mcp-server-openfda",
        "run",
        "mcp-server-openfda"
      ]
    }
  }
}
```

## Git/auth state

- Global user.name: `Umang Jani`
- Global user.email: `umangjani215@gmail.com`
- GitHub authenticated via `gh` as `Janiumang` (keyring-backed)
- `gh auth status` should show: `Logged in to github.com account Janiumang`
