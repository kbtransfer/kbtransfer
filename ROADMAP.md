# KBTRANSFER — v1 Implementation Roadmap

**Status:** Planning locked 2026-04-14. Implementation not yet started.
**Positioning:** Open protocol + reference implementation.
**Licenses:** Apache-2.0 (code), CC-BY-SA-4.0 (spec).

---

## Vision in one paragraph

A local-first knowledge base platform where every user keeps their own
Karpathy-style markdown wiki, and their AI agents can both **contribute to
it** (ingest sources, write pattern pages, log decisions and failures) and
**consume verified knowledge packs** distilled from other users' wikis.
Sharing is cryptographically signed per the AutoEvolve Pack spec v0.1.1
and distributed through a git-based registry (GitHub repo). Three tiers
(individual / team / enterprise) share the same protocol but scale
redaction strictness, trust posture, and review gates with the user's
compliance needs.

---

## Architecture summary

```
┌─────────────────────────────────────────────────────────────┐
│  KB MCP Server (stdio, local process)                       │
│  Tools: kb/search, read, write, ingest_source, lint,        │
│         subscribe, verify, draft_pack, distill, publish,    │
│         policy_get, policy_set                              │
└─────────────────────────────────────────────────────────────┘
                          ↓ reads/writes
┌─────────────────────────────────────────────────────────────┐
│  my-kb/  (plain markdown + git, user-owned)                 │
│  ├── .kb/          config (tier, policy, trust, schema)     │
│  ├── sources/      raw immutable inputs                     │
│  ├── wiki/         Karpathy-style living knowledge          │
│  │   ├── patterns/       reference                          │
│  │   ├── decisions/      EXPERIENCE (first-class)           │
│  │   ├── failure-log/    EXPERIENCE (first-class)           │
│  │   ├── entities/                                          │
│  │   └── log.md                                             │
│  ├── subscriptions/  isolated read-only signed packs        │
│  ├── drafts/         in-progress pack candidates            │
│  └── published/      outgoing signed pack tarballs          │
└─────────────────────────────────────────────────────────────┘
                          ↕ git push/pull
┌─────────────────────────────────────────────────────────────┐
│  GitHub: kb-registry template repo                          │
│  ├── publishers/{did}/keys.json     trust anchor            │
│  ├── packs/{pack_id}/{version}.tar  signed tarballs         │
│  └── index.json                     regenerated on merge    │
└─────────────────────────────────────────────────────────────┘
```

---

## Tier matrix (the single source of behavior)

Every tier-dependent decision flows from `.kb/tier.yaml`.

| Dimension              | individual         | team                 | enterprise              |
|------------------------|--------------------|----------------------|-------------------------|
| Trust default          | TOFU               | TOFU + warning       | strict allowlist        |
| Distiller pipeline     | manual checklist   | single-model LLM     | dual-model adversarial  |
| Redaction level        | minimal            | standard             | strict / paranoid       |
| Human review gate      | none               | 1 reviewer           | 2 reviewers + legal     |
| Default publish target | public GH registry | team git registry    | private registry        |

---

## Phased delivery

### Phase 1 — Wiki + MCP server skeleton (weeks 1–2)

**Goal:** a user can `kb init` a fresh KB, their agent can ingest sources,
search across wiki, read/write pages, and run lints. No packs yet.

**Deliverables:**
- `kb` CLI: `init`, `lint`, `doctor`.
- MCP server process (stdio transport) exposing:
  - `kb/search` — ripgrep over `wiki/` and (stubbed) `subscriptions/`.
  - `kb/read` — return a markdown page by path.
  - `kb/write` — create/update a wiki page.
  - `kb/ingest_source` — agent-driven source → wiki integration (the Karpathy flow).
  - `kb/lint` — contradiction / orphan / stale-claim health check.
  - `kb/policy_get`, `kb/policy_set` — read/write `.kb/policy.yaml`.
- Default `.kb/schema.yaml` with `patterns/`, `decisions/`, `failure-log/`,
  `entities/`, `sources/`, `log.md` as required skeleton.
- One end-to-end dogfood: drop a source, agent ingests, wiki grows, lint passes.

**Exit criteria:**
- Fresh clone, three commands to a working KB.
- At least one `decisions/` and one `failure-log/` page written by an agent
  during dogfood.
- MCP server works from Claude Code and at least one non-Claude MCP client.

### Phase 2 — Pack pipeline + isolated subscriptions (weeks 3–4)

**Goal:** a user can turn a wiki slice into a signed pack and a different
user can subscribe to that pack and query it alongside their own wiki.

**Deliverables:**
- Pack format per spec v0.1.1 §2–5: manifest, pack.lock with two merkle roots,
  four required attestations, Ed25519 envelope signatures.
- Verifier per spec v0.1.1 §6: seven-step procedure, offline, ~500 lines.
- Distiller (tier-aware):
  - individual: manual checklist + regex scrubber + user-confirm gate.
  - team: single-model LLM pass with residual-risk articulation.
  - enterprise: dual-model bias-isolated (Claude redactor + GPT verifier)
    per spec v0.1.1 §13, with required human-review gate.
- New MCP tools:
  - `kb/draft_pack` — select wiki slice, scaffold `drafts/{pack_id}/`.
  - `kb/distill` — run tier's pipeline, produce redacted + attested pack.
  - `kb/publish` — sign, write to `published/`, optional registry push.
  - `kb/subscribe` — fetch tarball (URL or local path), verify, drop into
    `subscriptions/{publisher}/{pack_id}/{version}/`.
  - `kb/verify` — standalone re-verification of any subscribed pack.
- `kb/search` extended: results tagged `mine` or `from:<did>`; policy can
  scope queries.
- Adversarial test suite: T1–T8 per v0.1.1 dogfood (T8 key-compromise is
  the load-bearing test — not optional).

**Exit criteria:**
- Round-trip: publisher A drafts → distills → publishes; publisher B
  subscribes → verifies → their agent's search hits both sources, labeled.
- T8 key-compromise test passes.
- Two publishers, two distinct keypairs, one cross-publisher dependency.

### Phase 3 — Git registry + trust inheritance (weeks 5–6)

**Goal:** publish and discover packs through a GitHub-hosted registry, with
marketplace-grade trust policies that handle transitive dependencies.

**Deliverables:**
- `kb-registry` GitHub template repo layout:
  - `publishers/{did}/keys.json` — trust anchor, verified at merge time.
  - `packs/{pack_id}/{version}.tar` — LFS-backed signed tarballs.
  - `index.json` — regenerated by CI on every merge.
- GitHub Actions:
  - Pre-merge: run full v0.1.1 §6 verification on submitted pack; block
    merge on any failure.
  - Post-merge: rebuild `index.json`, publish release, notify webhooks.
- Federation in the MCP server:
  - `kb/search --registry <git-url>` — federated search across multiple
    registries, preference order per policy.
  - Registry cache under `.kb/registry-cache/` with TTL.
- v0.1.2 spec amendments applied (from `03-dep-chain-report.md`):
  - `trust_inheritance` policy: `strict | inherit-from-parent | namespace-scoped`.
  - Defense-in-depth layers section (§5.4 new).
  - B5 reclassified as integrity sanity check.
  - Dependency-path breadcrumbs in verifier errors.
  - `max_depth` policy option.
  - Registry hint URL schemes standardized.
- Dependency chain dogfood: D1–D6 per `03-dep-chain-report.md`.

**Exit criteria:**
- A fresh user can `kb subscribe <pack_id> --from https://github.com/.../kb-registry`
  and receive a verified pack.
- Enterprise tier with strict allowlist rejects unknown transitive publishers.
- Individual tier with inherit-from-parent resolves the same chain successfully.
- All 30+ adversarial tests (T1–T8 + D1–D6 + trust_inheritance variants) pass.

---

## Cross-cutting concerns

**Testing strategy.** Each phase ships its own dogfood script producing a
real pack with real Ed25519 keys. No mocks. Adversarial tests run in CI.

**Spec versioning.** v0.1.1 is authoritative for Phase 1–2. v0.1.2
amendments land with Phase 3; `specs/current/` is updated in the same PR
that ships the supporting code.

**MCP tool stability.** Every MCP tool name includes a `/0.1` suffix (per
registry spec §3). Breaking changes require `/0.2` parallel tool until
migration is complete.

**Security posture.** Ed25519 only in v1 (per spec). Key storage is
user responsibility; `kb init` generates a keypair under
`.kb/keys/publisher-{date}.{pub,priv}` with `0600` perms. No network
calls during verification; trust bootstrap is explicit.

**Documentation that ships with code.** Each phase updates:
- `README.md` at repo root (top-level narrative).
- `docs/getting-started.md` (three-command onboarding).
- `docs/spec-v0.1.1.md` (authoritative pack format, moved into `specs/`).
- Tool-level README inside each implementation directory.

---

## Deferred to v2

These are explicit non-goals for v1; do not scope-creep:

- Payment rails / commercial pack billing.
- RFC 3161 external timestamping.
- Formal revocation protocol.
- Vector/semantic search in wiki (markdown + ripgrep is v1).
- Web UI / SaaS.
- Real-time pub/sub notifications for new pack versions.
- Multi-registry consortium trust protocols.
- Full RFC 8785 canonical JSON (canonical-2026-04 subset is v1).

---

## Repository layout after v1

```
KBTRANSFER/
├── README.md
├── ROADMAP.md                       ← this file
├── LICENSE-APACHE-2.0
├── LICENSE-CC-BY-SA-4.0
├── specs/
│   └── current/
│       ├── autoevolve-spec-v0.1.1.md
│       └── autoevolve-registry-spec-v0.1.md
├── reports/
│   ├── 01-v0.1-dogfood-feedback.md
│   ├── 02-v0.1.1-dogfood-report.md
│   └── 03-dep-chain-report.md
├── reference/                       ← Python reference implementation
│   ├── kb_cli/                      (Phase 1)
│   ├── kb_mcp_server/               (Phase 1–3)
│   ├── kb_pack/                     (Phase 2: build + verify)
│   ├── kb_distiller/                (Phase 2: tier-aware pipelines)
│   └── kb_registry/                 (Phase 3: GH Actions + index)
├── tests/
│   ├── adversarial/                 (T1–T8, D1–D6, trust_inheritance)
│   └── integration/                 (end-to-end dogfood scripts)
└── examples/
    └── kb-template/                 (what `kb init` produces)
```

---

## Immediate next steps

1. Restructure repo: move spec docs into `specs/current/`, reports into `reports/`.
2. Add licenses, top-level README pointing at this roadmap.
3. Scaffold `reference/` with empty packages for Phase 1 work.
4. Start Phase 1 implementation with `kb init` and `.kb/schema.yaml` default.

*End of v1 roadmap.*
