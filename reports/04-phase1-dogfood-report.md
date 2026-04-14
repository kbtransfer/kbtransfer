# Phase 1 Dogfood Report

**Scope:** `kb init` + `kb-mcp` server + seven `kb/*` tools from the
v1 roadmap.
**Target:** single-user, single-KB Karpathy flow (ingest → integrate
→ lint) plus the subscription-tagging contract from the locked design
decisions.
**Status:** 29 / 29 tests passing. Phase 1 functionally complete.

---

## 1. What was built

Two Python packages, scaffolded templates, and a Phase-1 tool
surface glued together by a stdio MCP server:

```
reference/
├── kb_cli/
│   ├── cli.py               click group: kb --version, kb doctor
│   ├── init.py              kb init with tier-aware scaffold
│   ├── keygen.py            Ed25519 keypair generator (0600 private)
│   └── templates/           schema + policy/{tier}.yaml + wiki skeleton
└── kb_mcp_server/
    ├── server.py            low-level Server + stdio transport
    ├── kb_root.py           KB root resolution (arg / env / cwd)
    ├── envelope.py          {ok, data, error} response envelope
    └── tools/
        ├── search.py        kb/search/0.1       — tagged results
        ├── read.py          kb/read/0.1         — path-sandboxed
        ├── write.py         kb/write/0.1        — auto-logs to wiki/log.md
        ├── ingest_source.py kb/ingest_source/0.1 — Karpathy reading plan
        ├── lint.py          kb/lint/0.1         — schema-driven findings
        ├── policy_get.py    kb/policy_get/0.1   — read policy.yaml
        └── policy_set.py    kb/policy_set/0.1   — dotted-path update
```

Everything ships under Apache-2.0; templates ship under CC-BY-SA-4.0
via `LICENSE.md`.

## 2. Locked design decisions honored

Each of the ten decisions from 2026-04-14 has a concrete anchor in
Phase 1 code.

| # | Decision                                 | Anchor |
|---|------------------------------------------|--------|
| 1 | Mixed tiers (individual / team / enterprise) | three policy templates under `templates/kb/policy/` |
| 2 | MCP server, protocol-agnostic            | `kb_mcp_server.server.build_server`, stdio transport |
| 3 | Plain markdown + git                     | every write lands as markdown; no DB dependency |
| 4 | Git-based registry (deferred to Phase 3) | subscriptions layout under `subscriptions/{publisher}/...` anticipates it |
| 5 | Tier-dependent distiller (Phase 2)       | `publisher.distiller_mode` key present in all three policies |
| 6 | Pattern granularity                      | `wiki/patterns/README.md` documents the 5-page pattern shape |
| 7 | Open protocol + reference impl           | `LICENSE.md`, `LICENSE-APACHE-2.0`, `LICENSE-CC-BY-SA-4.0` |
| 8 | Tier-dependent trust default             | `trust.model = tofu` (ind/team) vs `allowlist` (enterprise) |
| 9 | `decisions/` + `failure-log/` first-class | enforced `required: true` in `.kb/schema.yaml`; lint rejects removal |
|10 | Isolated, read-only subscriptions        | `kb/write/0.1` rejects `subscriptions/*`; `kb/search/0.1` tags hits as `from:<publisher>` |

## 3. Canonical end-to-end flow

`tests/integration/test_phase1_e2e.py` scripts a realistic agent
session against a `team`-tier KB:

1. Ingest a "Postgres replication lag incident" source via
   `kb/ingest_source/0.1`. Source lands under `sources/` with a
   timestamped, slugified filename and YAML frontmatter.
2. Read the source back via `kb/read/0.1`.
3. Compose three pages — one in `patterns/`, one in `decisions/`,
   one in `failure-log/` — via three `kb/write/0.1` calls. Each
   write auto-appends to `wiki/log.md`.
4. Search for "replication" with `kb/search/0.1`; confirm every hit
   is tagged `source: mine`.
5. Plant a fake subscription under
   `subscriptions/did-web-dba-foundation/postgres-ha/1.2.0/`. Search
   for "lag" across everything; confirm hits now include both `mine`
   and `from:did-web-dba-foundation`.
6. Run `kb/lint/0.1`; expect zero errors, maybe some orphan warnings
   for the brand-new pages (they link to each other; they should not
   be orphans by design).
7. Round-trip the policy via `kb/policy_get/0.1` + `kb/policy_set/0.1`
   — verify the YAML on disk reflects the change.

All seven steps pass.

## 4. Transport-level smoke

`tests/integration/test_stdio_smoke.py` launches
`python -m kb_mcp_server --root <tmp>` as a subprocess and drives it
through the official `mcp.ClientSession`. It lists tools (7 returned,
all with the expected names + version suffixes) and calls
`kb/policy_get/0.1`. This is the canonical "does Claude Code / Cursor
see the surface?" check — passes under Python 3.14 + `mcp==1.27.0`.

## 5. Findings

### 5.1 Keyword extraction is frequency-ranked, not salience-ranked

The initial draft of the dogfood asserted `"postgres" in keywords`
for a source that mentioned "Postgres" only twice. The tokenizer did
pick it up, but it tied with many 1-count words and was sorted out
alphabetically before the top-20 cutoff. Test now asserts on
`"replication"` (3+ mentions) which is stable.

**Implication for Phase 2 / distiller work:** the in-tool keyword
extractor is deliberately simple (no TF-IDF, no embeddings). That's
fine for a reading plan but it means the agent, not the extractor,
is responsible for noticing that a low-frequency proper noun is the
important thing to anchor a pattern page on. Document this in the
`ingest_source` tool description before handing the surface to
external agents.

### 5.2 wiki/log.md append is cheap but correct

The design decision to auto-append a log line on every wiki write
turned out clean to implement (one function, ~10 lines) and
immediately useful: after the dogfood's three writes, `wiki/log.md`
held three timestamped entries and the page count in the lint report
matched the entries. Consider making this the primary audit surface
for the enterprise tier in Phase 2, rather than a separate JSON
ledger.

### 5.3 Path sandboxing is load-bearing

`kb/read/0.1` and `kb/write/0.1` both rely on
`Path.relative_to(root)` to reject escapes. The sandbox tests
(`test_read_rejects_escape_outside_kb`,
`test_read_rejects_kb_config_read`,
`test_write_rejects_subscription_paths`) caught a subtle early bug:
an earlier draft used `requested.startswith("wiki/")` for
authorization, which would have let `wiki/../.kb/policy.yaml` leak.
The `Path` + `READABLE_ROOTS` / `WRITABLE_ROOTS` sets are the right
primitive.

### 5.4 Two `__init__.py` style gotcha

`reference/kb_mcp_server/tools/__init__.py` uses inline relative
imports (`from . import search as _search, ...`). This was cleaner
than a dynamic registry but means each new tool requires touching
two files (the module itself and the `_MODULES` list). Acceptable
for a 7-tool surface; revisit if the surface exceeds ~20 tools in
later phases.

## 6. Spec amendments surfaced (queued for v0.1.2)

None from Phase 1. The spec work done in v0.1.1 + the three prior
dogfood reports had already absorbed every gap this phase could
reach.

## 7. What's explicitly NOT proven

- **No pack format code yet.** `kb/draft_pack` and `kb/publish` are
  Phase 2. The subscriptions folder layout in Phase 1 is a mock; the
  Phase 2 verifier will be the one enforcing signatures and content
  roots.
- **No distiller.** `kb/ingest_source/0.1` is the Karpathy read-in
  side. The wiki → pack distillation pipeline is Phase 2, with three
  tier-dependent modes per the locked decisions.
- **No registry.** Discovery across users requires the Phase 3 git
  registry + trust inheritance work.
- **No contradictions / stale-claims lint.** Scaffolded in
  `kb/lint/0.1` but not actionable without agent input in Phase 1.

## 8. Cumulative status

| Artifact                        | Status                      |
|---------------------------------|-----------------------------|
| Repo layout                     | Per ROADMAP                 |
| Licenses                        | Apache-2.0 + CC-BY-SA-4.0   |
| Python reference scaffold       | 5 packages, `pyproject.toml`|
| `kb` CLI                        | `init`, `doctor`, `--version` |
| `kb-mcp` server                 | stdio, 7 tools              |
| Tests                           | 29 / 29 passing             |
| Dogfood flow                    | Full Karpathy cycle verified |
| Phase 2 readiness               | Ready — pack format + distiller next |

## 9. Deliverables in this iteration

```
Phase-1/
├── reference/kb_cli/                  (commands, templates, keygen)
├── reference/kb_mcp_server/           (server + 7 tools)
├── tests/test_cli_smoke.py            (3 tests)
├── tests/test_init.py                 (8 tests)
├── tests/test_mcp_tools.py            (16 tests)
├── tests/integration/test_phase1_e2e.py   (1 end-to-end flow)
├── tests/integration/test_stdio_smoke.py  (1 transport smoke)
└── reports/04-phase1-dogfood-report.md    (this file)
```

---

*End of Phase 1 dogfood report. Phase 2 — pack pipeline + isolated
subscriptions — starts next.*
