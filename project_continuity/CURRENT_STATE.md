# Current State Snapshot

**Last updated:** end of Session 01 (2026-05-06)
**Latest commit on `main`:** `f4467d9`

## Repo layout

```
mcp-server-openfda/
├── .gitignore                       # Python defaults + .DS_Store
├── .python-version                  # 3.11
├── LICENSE                          # MIT
├── README.md                        # Public description (untouched this session)
├── pyproject.toml                   # Project metadata + dependencies
├── uv.lock                          # Locked dep versions (committed)
├── .venv/                           # Local virtual env (gitignored)
├── src/
│   └── mcp_server_openfda/
│       ├── __init__.py              # Re-exports main
│       └── server.py                # FastMCP server + ping tool
└── project_continuity/              # Working notes (this folder)
    ├── SESSION_01_SUMMARY.md
    ├── CURRENT_STATE.md
    ├── NEXT_STEPS.md
    ├── DECISIONS_LOG.md
    └── OPEN_ISSUES.md
```

## Dependencies

Direct: `mcp[cli]>=1.27.0`.
Transitive (via mcp): pydantic, httpx, starlette, anyio, click, typer, rich, jsonschema, sse-starlette, uvicorn, python-dotenv, python-multipart, pyjwt, cryptography, etc. — see `uv.lock` for the full pinned list.

## MCP server identity

- **Server name (Claude Desktop):** `signalbridge-openfda`
- **Python package:** `mcp_server_openfda`
- **Console script:** `mcp-server-openfda` (defined in `pyproject.toml [project.scripts]`)
- **Entry point:** `mcp_server_openfda:main` → `mcp.run()` → stdio JSON-RPC loop

## Tools currently exposed

| Tool name | Purpose | Status |
|-----------|---------|--------|
| `ping` | Verify MCP wiring, return a fixed string | Live |

## Tools planned for v0.1 (not yet built)

- `search_drug_adverse_events` — FAERS query with filters
- `count_adverse_events` — aggregate counts via openFDA `count` parameter
- `get_drug_label` — drug label retrieval
- `search_drug_recalls` — recalls by drug or firm

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
