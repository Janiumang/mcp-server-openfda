# NEXT SESSION — START HERE

**Resume point:** v0.1 is feature-complete. Two parked items remain before tagging v0.1.0, both deliberately written in Jani's voice (not Claude's) per the brief's no-ghostwriting rule.

## Status going in

- Six tools live and smoke-tested.
- Eight commits on main, clean conventional-commits history.
- `pyproject.toml` metadata correct (description filled in, version `0.1.0`).
- All session 02/03 work committed and pushed.

## Most likely next 2 actions

### 1. README pass (Jani writes the prose)

The README on `main` was written before any code shipped. It now needs to reflect what actually exists. Suggested structure that Claude can offer to critique once Jani has a draft:

- **Title / one-liner.** "SignalBridge for openFDA — MCP server exposing openFDA pharmacovigilance data."
- **What it is, in one paragraph.** What openFDA is, what an MCP server is, why a PV person would care.
- **What it does (v0.1).** List the six tools with one-line descriptions each. The tool docstrings inside server.py are good source material to paraphrase.
- **The README's example query.** Re-run "What is the public FDA safety profile of pembrolizumab in patients over 65 during the last 5 years?" Show actual output (count, top reactions, class breakdown). This is the proof that the tool does PV work, not just JSON shuffling.
- **Quick start.** `git clone`, `uv sync`, Claude Desktop config snippet (the same `mcpServers` block we ironed out in Session 01).
- **OPENFDA_API_KEY note.** Optional, raises rate limit.
- **Limitations.** Honest list: MedDRA pass-through (v0.2 will add mapping), most-recent-label-only (no manufacturer scoping), drug-only (no device, no food, no VAERS), naive rate-limit handling.
- **Roadmap.** v0.2 candidates (MedDRA mapping, manufacturer scoping). VAERS as a future separate `mcp-server-vaers` connector under the SignalBridge umbrella. Other regulators (EMA, MHRA, PMDA, Health Canada) as the longer-term family.
- **Built with.** "Co-built with Claude as pair-programmer" — per Jani's brief, this is good signal for AI-role applications, not bad. Link to the conventional-commits history.
- **License.** MIT, link to LICENSE file.

Claude's role on this pass: critique structure, point out gaps, flag any overclaim (anything in the README not actually in the code). NOT writing the prose.

### 2. (Optional) Tag v0.1.0

Once the README lands:

```bash
git tag -a v0.1.0 -m "v0.1.0 - feature-complete openFDA MCP connector"
git push --tags
```

## Polish items not in v0.1 scope

- Test strategy / first test file. Use `engineering:testing-strategy` skill before any tool code in v0.2.
- Cross-machine reproducibility check (clone fresh, `uv sync`, run tests on a non-Apple-Silicon machine).
- Anything in `OPEN_ISSUES.md` under "Deferred to v0.2."

## Skills to invoke when resuming

- `engineering:code-review` — review all four tools side-by-side once before tagging v0.1.0. Focus on consistency: do all four tools handle errors the same way, return the same response shape conventions, document limitations the same way?
- `engineering:testing-strategy` — design a v0.2 test plan now that all four tool patterns are stable.
- `regulatory-compliance-quality-guardrail-skill` — final pass on README to make sure no claim exceeds what's shipped.
- The README pass itself: no skill needed; Jani writes, Claude critiques.

## Open architectural questions for v0.2

1. **MedDRA mapping.** Pass-through-with-documented-limitation worked for v0.1. v0.2 needs a real mapping. License/IP review before any code reuse from VigilantAI; default is to rebuild rather than vendor.
2. **Manufacturer-aware label queries.** Currently `get_drug_label` returns the most recent label by effective_time regardless of manufacturer. Adding an optional `manufacturer` filter would let PV reviewers see the innovator label specifically when generics exist.
3. **Rate-limit handling.** Naive in v0.1. v0.2 should add retry-with-exponential-backoff on HTTP 429.
4. **Test coverage.** None today. Pick a strategy (mock openFDA vs. live snapshot replay) before writing the first test.
5. **VAERS connector.** Own repo (`mcp-server-vaers`) under SignalBridge umbrella. Different schema, different upstream system.
