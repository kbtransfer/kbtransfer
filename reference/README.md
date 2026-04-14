# reference/ — KBTRANSFER Reference Implementation

Python packages that realize the protocol described under
[`../specs/current/`](../specs/current/). Apache-2.0 licensed.

## Package map

| Package | Purpose | Phase |
|---------|---------|-------|
| `kb_cli`         | Command-line entry point: `kb init`, `kb lint`, `kb doctor` | 1 |
| `kb_mcp_server`  | Stdio MCP server exposing the `kb/*` tool surface           | 1–3 |
| `kb_pack`        | Build + verify per AutoEvolve pack spec v0.1.1              | 2 |
| `kb_distiller`   | Tier-aware distillation pipeline (manual / single / dual)    | 2 |
| `kb_registry`    | Git-based registry tooling + CI verification                 | 3 |

Each package has its own `README.md` once it contains real code.

## Design anchors

- **Offline-first.** No package requires network access for the core
  verification path. Trust bootstrap is explicit.
- **Markdown is truth.** Indexes, caches, and lock files exist for
  speed; the user's wiki is always a self-sufficient folder of
  markdown.
- **Spec is authoritative.** If code and spec disagree, the spec wins
  for semantics; the reference implementation is the tiebreaker only
  for ambiguities explicitly deferred to it (spec Appendix D).
