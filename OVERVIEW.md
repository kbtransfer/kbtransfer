# KBTRANSFER — Project Overview

> Open-protocol federated knowledge base between AI agents.
> Karpathy-style markdown wiki + AutoEvolve Pack distillation +
> verifiable cross-org sharing — local-first, signed, MCP-native.

This document is the single-page tour of the project: what it is, why
it exists, how it is built, and how to use it. For deeper material
follow the cross-references — every section names the file you want
to read next.

**Status snapshot (2026-04-15, commit `218c155`):** v1 reference
implementation complete, v2 RFC track planned (Phase 4-6, six
medium-depth RFCs), single-model + dual-model distiller skills
shipped. 134 / 134 tests passing + 4 live-LLM canaries skipped
behind an env flag. Apache-2.0 (code) + CC-BY-SA-4.0 (specs). Local
repo only — no remote push yet.

---

## 1. The problem

Two well-known patterns each solve half of the agent-knowledge
problem; nothing currently bridges them.

- **Karpathy's LLM Wiki** (intra-agent, single-user). An LLM
  maintains a living markdown wiki that compounds over time instead
  of rediscovering knowledge per query. See the
  [original gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
  Solves "my agent forgets across sessions." Does not solve "my
  agent should benefit from your team's hard-won knowledge."
- **AutoEvolve Packs** (inter-agent, cross-org). Pattern-level
  knowledge packs, Ed25519-signed, four-attestation, redacted by a
  bias-isolated pipeline, verifiable offline. The format spec lives
  under [`specs/current/`](./specs/current/). Solves "send a slice
  of my knowledge somewhere the recipient can verify it." Does not
  solve "where does the knowledge live day-to-day."

KBTRANSFER is the missing bridge: the live wiki where knowledge
grows, the distillation pipeline that turns a slice of that wiki
into a shareable pack, and the consumption layer that imports other
people's packs without polluting your own wiki.

## 2. What makes it different

Six choices that downstream everything else.

1. **Experience is first-class.** The default wiki schema reserves
   two dedicated folders alongside the usual `patterns/` and
   `entities/`: `decisions/` and `failure-log/`. Reference docs can
   be rediscovered from public sources; what a team actually tried,
   what broke, and why they chose X over Y cannot. Enforced via
   `.kb/schema.yaml` `required: true`.
2. **One protocol, three tiers.** Individual developers, small
   teams, and regulated enterprises share the same pack format but
   scale redaction strictness, trust posture, and review gates to
   match their compliance needs. A single `.kb/tier.yaml` drives
   every tier-dependent behavior.
3. **MCP-native.** The reference implementation ships as an MCP
   stdio server. Claude Code, Cursor, Claude Desktop, and any
   MCP-aware agent can drive it without a custom adapter.
4. **Plain markdown + git.** User data is a folder of markdown files
   tracked by git. No database owns the truth. A git clone is a
   complete backup; a git diff is a complete audit trail.
5. **Registry is untrusted.** Registries discover, resolve, and
   distribute packs but are never the trust root. Every pack is
   re-verified consumer-side from publisher signatures. Registry
   compromise = denial of service, not silent compromise.
6. **Subscriptions are isolated read-only.** Imported packs live
   under `subscriptions/{publisher}/{pack}/{version}/` — never
   merged into your own wiki, never silently mutated. Search results
   are tagged `mine` vs `from:<did>` so an agent always knows
   provenance.

For the original ten v1 design decisions and the ten v2 design
decisions made on 2026-04-15, see
[`memory/design_decisions_v1.md`](./memory/design_decisions_v1.md)
and `memory/design_decisions_v2_2026_04_15.md`.

## 3. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code, Cursor, Claude Desktop, ...)        │
│  + Optional Claude Code Skills:                             │
│    - kb-distill              single-model team-tier loop    │
│    - kb-distill-adversarial  dual-model enterprise loop     │
└──────────────────────────────┬──────────────────────────────┘
                               │ MCP stdio
┌──────────────────────────────▼──────────────────────────────┐
│  KB MCP Server (kb-mcp, local process)                      │
│  15 tools under kb/* namespace; see §5                      │
└──────────────────────────────┬──────────────────────────────┘
                               │ reads/writes
┌──────────────────────────────▼──────────────────────────────┐
│  my-kb/  (plain markdown + git, user-owned)                 │
│  ├── .kb/          tier, policy, schema, trust store, keys  │
│  ├── sources/      raw immutable inputs (PDFs, transcripts) │
│  ├── wiki/         Karpathy-style living knowledge          │
│  │   ├── patterns/       reference                          │
│  │   ├── decisions/      EXPERIENCE (first-class)           │
│  │   ├── failure-log/    EXPERIENCE (first-class)           │
│  │   ├── entities/                                          │
│  │   └── log.md          chronological journal              │
│  ├── subscriptions/  isolated read-only signed packs        │
│  ├── drafts/         in-progress pack candidates            │
│  └── published/      outgoing signed pack tarballs          │
└──────────────────────────────┬──────────────────────────────┘
                               │ git push/pull or HTTPS
┌──────────────────────────────▼──────────────────────────────┐
│  Registry (git-based, file://, https:// all supported)      │
│  ├── publishers/{did}/keys.json     trust anchor            │
│  ├── packs/{pack_id}/{version}.tar  signed tarballs         │
│  ├── index.json                     regenerated on merge    │
│  └── (v2) federation.json           federation graph        │
└─────────────────────────────────────────────────────────────┘
```

Five Python packages under `reference/` implement the server side:

| Package | Purpose |
|---|---|
| `kb_cli` | `kb` command (init, doctor) + tier-aware scaffolding + Ed25519 keygen |
| `kb_mcp_server` | stdio MCP server hosting the 15 `kb/*` tools |
| `kb_pack` | manifest, canonical JSON, Merkle roots, signing, verification, recursive dependency verification with trust inheritance |
| `kb_distiller` | regex scrubber, tier-aware pipeline (manual / single-model / dual-model), model-family classifier (`family.py`) |
| `kb_registry` | registry client (`file://`, bare path, `https://`, `git+https://`) with semver resolution + index builder; HTTPS transport verifies every tarball against the index-declared sha256 before extraction |

## 4. The three tiers

Every tier-dependent decision flows from `.kb/tier.yaml` and the
matching `.kb/policy.yaml` template under
`reference/kb_cli/templates/kb/policy/`.

| Dimension | individual | team | enterprise |
|---|---|---|---|
| Trust model | TOFU | TOFU + warn | strict allowlist; TOFU off |
| Redaction floor | minimal | standard | strict |
| Distiller mode | `manual` (regex + checklist) | `single-model` (LLM paraphrase) | `dual-model` adversarial |
| Verifier family must differ | n/a | n/a | yes (enforced by `publish.py`) |
| Human review | none | optional | required (≥2 reviewers + legal) |
| License default | Apache-2.0 | publisher-set | `LicenseRef-internal-commercial` |
| Min dependency depth | n/a | 8 | 4 |
| Audit trail required | no | no | yes |

The same MCP tools work across all tiers; only the policy + the
distiller path the agent takes change.

## 5. The 15 MCP tools

All tools are stable at version `0.1` and namespaced under `kb/*`.
Source: `reference/kb_mcp_server/tools/`.

### Wiki layer (write & read your own KB)

| Tool | Purpose |
|---|---|
| `kb/search/0.1` | Full-text search across `wiki/` + `subscriptions/`; results tagged `mine` vs `from:<did>` |
| `kb/read/0.1` | Path-sandboxed read of any file under the KB root |
| `kb/write/0.1` | Write a markdown page; auto-appends to `wiki/log.md` |
| `kb/ingest_source/0.1` | Karpathy-style "reading plan" against a raw source under `sources/` |
| `kb/lint/0.1` | Schema-driven findings against `.kb/schema.yaml` |
| `kb/policy_get/0.1` | Read the active `.kb/policy.yaml` |
| `kb/policy_set/0.1` | Update a single dotted-path key in policy |

### Pack lifecycle (publish your knowledge)

| Tool | Purpose |
|---|---|
| `kb/draft_pack/0.1` | Initialize a draft under `drafts/<pack_id>/` from a wiki-slice query |
| `kb/distill/0.1` | Run the tier-aware distillation pipeline; persists `.distill-report.json` |
| `kb/publish/0.1` | Seal a draft into a signed tarball under `published/`; populates 4 attestations |

### Consumption + verification

| Tool | Purpose |
|---|---|
| `kb/subscribe/0.1` | Import a pack into `subscriptions/...` (filesystem path or registry-mode) |
| `kb/verify/0.1` | Verify a pack against trust store + policy; recursive dependency verification with trust inheritance + breadcrumbs on failure |

### Registry (discovery + resolution)

| Tool | Purpose |
|---|---|
| `kb/registry_describe/0.1` | Self-description of a registry (role, counts, contact) |
| `kb/registry_search/0.1` | Search packs across a registry by query + filters |
| `kb/registry_resolve/0.1` | Given pack_id + semver constraint, return the best matching version + fetch metadata |

The v2 RFC track adds `kb/registry_submit/0.1`,
`kb/registry_federation/0.1`, and `kb/check_revocations/0.1` plus
extends a few existing tools. See [`ROADMAP-v2.md`](./ROADMAP-v2.md).

## 6. Knowledge base layout

A KB is the directory created by `kb init`. Every concept here maps
to a folder on disk; nothing is hidden in a database.

```
my-kb/
├── .kb/
│   ├── tier.yaml          tier choice + publisher id + signing key id
│   ├── policy.yaml        tier-specific consumer + publisher rules
│   ├── schema.yaml        wiki schema (required folders, field rules)
│   ├── trust-store.yaml   allowlisted publishers + their keys
│   └── keys/              Ed25519 keypair for this KB's pack signing
├── sources/               raw immutable inputs (PDFs, transcripts, ...)
├── wiki/
│   ├── patterns/          reference docs + how-to patterns
│   ├── decisions/         first-class: what we tried, what we picked, why
│   ├── failure-log/       first-class: what broke, root cause, what we changed
│   ├── entities/          people, systems, domains
│   └── log.md             chronological journal (auto-appended by kb/write)
├── subscriptions/         isolated read-only imported packs
│   └── {publisher_did_safe}/{pack_id}/{version}/
├── drafts/                in-progress pack candidates
│   └── {pack_id}/
│       ├── pages/             markdown going into the pack
│       ├── attestations/      built by kb/publish
│       ├── pack.manifest.yaml
│       └── .distill-report.json   build-time artifact, not shipped
└── published/             outgoing signed tarballs
    └── {pack_id}-{version}.tar
```

## 7. Trust model

The trust model is built around four compounding ideas:

1. **Ed25519 signing.** Every pack is signed by its publisher's
   private key. The corresponding public key is identified by a
   `key_id` and lives in the publisher's DID document and (cached
   form) in the registry.
2. **Four attestations per pack.** Sealed at publish time:
   `provenance` (where it came from), `redaction` (how it was
   processed; carries `residual_risk_notes`), `evaluation` (test
   results, composite score), `license` (SPDX + class + grants).
   Each attestation is internally signed and pinned to the same
   `content_root`.
3. **Two roots.** `content_root` is the Merkle root of pack content
   (`pages/` + `pack.manifest.yaml`). `pack_root` is the Merkle
   root of the entire pack including attestations. Consumer
   recomputes both and checks them against the publisher signature.
4. **Recursive verification with trust inheritance.** A pack may
   depend on other packs. `kb/verify/0.1` walks the dependency graph
   (cap: `consumer.max_dependency_depth`); for each dep it applies a
   policy-driven trust inheritance rule:
   - `strict` — reject if dep's publisher not in your trust store.
   - `inherit-from-parent` — auto-trust up to `max_inherit_depth`
     levels using key bundled inside the dep's pack.
   - `namespace-scoped` — trust only when dep's pack_id falls under
     a configured namespace glob AND dep's publisher is allowed for
     that namespace.

   Failures carry breadcrumbs:
   `qr-offline@1.0.1 -> base.crypto@1.0.0 -> ...`

The eight v1 dogfood reports (`reports/01-06`) document what the
trust model resists. Adversarial test suites T1-T8 (key rotation,
revocation, downgrade, forgery, dependency-chain attacks) and D1-D6
(cross-publisher dependency, namespace boundary, trust-inheritance
abuse, registry lying) all pass; `tests/adversarial/` is the
authoritative inventory.

### v2 trust extensions (RFC track, planned)

The current trust story is solid for the v1 scope but defers four
items to v2. Each has a medium-depth RFC under `rfcs/`:

| RFC | Topic | What it adds |
|---|---|---|
| RFC-0003 | `did:web:` HTTPS resolution | Publisher's own DID document becomes the authoritative key source; registry's cache becomes advisory |
| RFC-0004 | RFC 3161 timestamping | TSA-signed `genTime` attached to attestations; "this was signed at time T" provable independent of publisher claims |
| RFC-0005 | Registry federation trust | Registries can declare mirrors + endorsements; consumer policy decides whether to honor them |
| RFC-0006 | Revocation protocol | Publisher publishes a signed revocation list; combined with RFC-0004 timestamps gives point-in-time-correct trust |

See [`ROADMAP-v2.md`](./ROADMAP-v2.md) for sequencing and the six
RFC files for technical details.

## 8. Pack format

A pack is a deterministic tarball with a single top-level directory
named `{pack_id}-{version}/` containing:

```
{pack_id}-{version}/
├── pack.manifest.yaml        pack id, version, license, dependencies, ...
├── pages/                    markdown content (the actual knowledge)
│   ├── 01-overview.md
│   └── ...
├── attestations/
│   ├── provenance.json       source documents, build environment
│   ├── redaction.json        level, policy applied, categories,
│   │                         residual_risk_notes (non-empty per amendment C1),
│   │                         optional llm_assisted_by + adversarial_verification
│   ├── evaluation.json       evaluators, test_cases, composite_score
│   └── license.json          SPDX, class, grants, restrictions, warranty
└── pack.lock                 frozen dependency hashes
```

The on-the-wire format is fully specified in
`specs/current/autoevolve-spec-v0.1.1.md`. Consumers re-derive
`content_root` and `pack_root` from the bytes on disk; nothing in
the pack is taken on faith from the publisher's claims.

## 9. The distillation pipeline

Distillation turns a wiki slice (under `drafts/<pack_id>/pages/`)
into something safe to share. The pipeline is tier-aware
(`reference/kb_distiller/pipeline.py`):

| Mode | Tier default | What it does |
|---|---|---|
| `manual` | individual | Regex scrubber + publisher checklist. No LLM. Deterministic. |
| `single-model` | team | Regex scrubber + LLM paraphrase + soft-signal redaction (client names, codenames, monetary amounts) |
| `dual-model` | enterprise | Single-model + bias-isolated adversarial verifier from a different model family |

The MCP server itself does not run LLM inference. Two Claude Code
skills under `examples/skills/` drive the LLM passes:

### `kb-distill` — single-model skill (3.a)

`examples/skills/kb-distill/SKILL.md`. Loop:

1. `kb/distill/0.1` — get findings + checklist.
2. **Strict regex-clearing loop** (max 3 iterations): for each
   finding, use the precise location fields
   (`line_start`/`line_end`/`char_start`/`char_end`) to fetch
   tight context, paraphrase to eliminate the placeholder, write
   back via `kb/write/0.1`. Re-run distill until findings = 0.
3. **Pass-2 residual review** (single LLM pass): scan every page
   for soft signals — client names, codenames, exact monetary
   amounts, stylometric fingerprints. Generalize in place.
4. Stamp `.distill-report.json` with `llm_assisted_by` block
   (model id, mode, iteration count, completion timestamps).
5. Hand back to user. Never auto-publishes.

### `kb-distill-adversarial` — dual-model skill (3.b)

`examples/skills/kb-distill-adversarial/SKILL.md`. Wraps the 3.a
loop with an adversarial verifier sub-call:

1. Pre-flight family check (using
   `kb_distiller.family.assert_different_families`).
2. Run 3.a's loop in full.
3. **Verifier loop** (max 3 iterations): for each rewritten page,
   compose 3-5 canary probes ("name the customer", "what dollar
   amount is mentioned"). Run a fresh verifier model (default
   `claude-haiku-4-5`; `VERIFIER_MODEL` env override for
   inter-provider use) against each probe. Any recovery above the
   policy threshold loops back to Pass-2 with a stricter prompt.
4. Stamp both `llm_assisted_by` (mode `dual-model`) AND
   `adversarial_verification` blocks in `.distill-report.json`.

### Family difference is server-enforced

The patent-relevant claim is *bias isolation* — the verifier and
redactor must come from different training families. Three layers
defend the invariant:

| Layer | Where | What it does |
|---|---|---|
| Skill pre-flight | SKILL.md Step 0 | Saves tokens; honest skills only |
| `_enforce_verifier_family_policy` | `publish.py` | Refuses to seal an attestation if policy demands family difference AND block names two same-family models — ignoring the skill's family claims and re-deriving from model ids |
| `assert_different_families` | `kb_distiller.family` | Single source of truth; unknown family is *refusal-to-classify*, not wildcard |

A skill that lies about which model it used is rejected at publish
time, not at runtime. The server is the trust root.

The model-family table currently covers Anthropic, OpenAI, Google,
Meta, Mistral, Cohere, DeepSeek, Alibaba, and xAI. Adding a new
family is a deliberate code change in
`kb_distiller/family.py:_FAMILY_PREFIXES`.

## 10. Registry & federation

A registry is a discovery + resolution + distribution surface — not
a trust root.

### v1: git-based registry (decision #4)

The reference template is `examples/sample-registry/` — a normal
GitHub repo containing:

```
sample-registry/
├── publishers/{did_safe}/keys.json     publisher trust anchors
├── packs/{pack_id}/{version}.tar       signed tarballs
├── index.json                          regenerated on merge
├── scripts/verify_submission.py        PR-time validator
└── .github/workflows/verify-pack.yml   CI gate
```

Publishing = open a PR with the new tarball + (first-time)
publishers entry. CI validates against the same checks
`kb/verify/0.1` runs locally. Operator merges. Index regenerates.
Zero infrastructure cost.

### Three operator roles (registry spec §2)

| Role | Submission | Use |
|---|---|---|
| Open | Permissionless (signature is the auth) | Public registries, npm-like |
| Consortium | Allowlisted publishers | Industry consortia, curated |
| Private | Org-internal + bearer token | Single-tenant, internal sharing |

The MCP API is identical across all three; only the
`describe()` response and the publisher allowlist change.

### v2 extensions (RFC track)

- **RFC-0001** — `https://` + `git+https://` transports. **Shipped** in `HttpsRegistry` (`reference/kb_registry/registry.py`).
- **RFC-0002** — `kb/registry_submit/0.1` MCP tool + `POST /v0.1/submit`
  wire endpoint. **Shipped** in `reference/kb_registry_server/` +
  `examples/sample-registry-http/` with `kb/publish/0.1` optionally
  pushing to a remote registry via `submit_to_registry`. Jointly
  closes Phase 4 with RFC-0001 (`reports/07-rfc0002-registry-submit.md`).
- **RFC-0005** — Federation graph: `federation.json` declares
  mirrors + endorsements + failover; consumer policy chooses
  whether to honor it. Phase 6.
- **RFC-0006** — Publisher revocation lists at
  `/.well-known/kbtransfer-revocations.json`; combined with
  RFC-0004 timestamps gives point-in-time-correct trust. Phase 6.

## 11. Subscription & consumption

Importing a pack does **not** merge it into your wiki. Subscriptions
land at:

```
subscriptions/{publisher_did_safe}/{pack_id}/{version}/
```

— same shape as the published pack on the publisher side, fully
read-only on the consumer side. Search results from `kb/search/0.1`
are tagged so the agent always knows: `tag: mine` vs
`tag: from:did:web:smartchip.ie`. Nothing silently flows from one
namespace to the other.

**`publisher_did_safe` encoding.** Canonical DIDs (e.g.
`did:web:smartchip.ie`) contain `:` which is an awkward path
character. `kb_pack.did_to_safe_path` defines the one-way transform
every tool uses: replace `:` and `/` with `-`; reject NUL, backslash,
and control characters. So `did:web:smartchip.ie` →
`did-web-smartchip.ie`. The transform is intentionally lossy — the
directory name is not a canonical identifier. Consumers that need
the original DID read `publisher.id` from the installed pack's
`pack.manifest.yaml`, or `.kb/trust-store.yaml`.

Consumption flow with verification:

1. `kb/registry_search/0.1` — find candidates.
2. `kb/registry_resolve/0.1` — pick a version satisfying a
   semver constraint.
3. `kb/subscribe/0.1` (registry-mode) — fetch the tarball,
   extract under `subscriptions/...`, run `kb/verify/0.1`.
4. `kb/verify/0.1` — recursive verification with trust
   inheritance per `.kb/policy.yaml`.
5. Now visible to `kb/search/0.1` (tagged `from:<did>`).

If verification fails at any depth, the breadcrumb tells the agent
exactly which dependency in the chain caused it.

## 12. Installation

Requires Python ≥ 3.11.

```bash
# Clone and install in dev mode (recommended for local iteration):
git clone <wherever-the-repo-lives> kbtransfer
cd kbtransfer
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Verify:
kb --version
kb-mcp --help
pytest -q              # 134 passing + 4 skipped
```

The two scripts installed are:

- `kb` — CLI for KB scaffolding and diagnostics.
- `kb-mcp` — stdio MCP server. Register it with your agent's MCP
  config (Claude Code: `claude mcp add kb-mcp kb-mcp`).

## 13. CLI reference

```bash
kb --version                        # print version
kb -h                               # full help

kb init <path> [--tier individual|team|enterprise]
              [--publisher-id did:web:<your-domain>]
              [--no-keygen]
              [--force]
   Scaffold a fresh KB. Generates an Ed25519 keypair under .kb/keys/
   unless --no-keygen. Default tier: individual.

kb doctor [--path <path>]
   Diagnostic snapshot of the KB at <path> (defaults to cwd).
   Lists .kb/ files and counts public keys.
```

The MCP server has its own entry point:

```bash
kb-mcp                              # serve on stdio
kb-mcp --root /abs/path/to/kb       # explicit KB root
                                    # (otherwise: env KB_ROOT, then cwd)
```

## 14. Skill installation (Claude Code only)

The two distiller skills live in the repo and are copied into your
Claude Code skills directory:

```bash
cp -r examples/skills/kb-distill              ~/.claude/skills/
cp -r examples/skills/kb-distill-adversarial  ~/.claude/skills/

# For 3.b: pick a verifier from a different family if your policy
# demands family difference (enterprise tier ships with this on):
export VERIFIER_MODEL="openai:gpt-4o"
```

Both skills assume `kb-mcp` is already registered. After install
they appear in Claude Code's `/` menu.

## 15. End-to-end workflow examples

### Publish a pack (team tier)

```text
1. kb init my-kb --tier team --publisher-id did:web:my-team.example
   cd my-kb
   git init && git add . && git commit -m "fresh KB"

2. # Drop a source under sources/, then in your agent:
   kb/ingest_source/0.1 path=sources/incident-2026Q1.md

3. # Agent writes wiki/decisions/use-circuit-breaker.md and
   # wiki/failure-log/snowfall-ingest-spike.md via kb/write/0.1.
   # Auto-appended to wiki/log.md.

4. kb/draft_pack/0.1 pack_id=my-team.patterns.circuit-breaker version=1.0.0
   # Pulls the relevant wiki pages into drafts/.../pages/.

5. # Run the single-model skill in Claude Code:
   /kb-distill my-team.patterns.circuit-breaker

6. # Skill drives kb/distill -> kb/read -> paraphrase -> kb/write loop,
   # then Pass-2 residual review, then stamps .distill-report.json.

7. kb/publish/0.1 pack_id=my-team.patterns.circuit-breaker
   # Seals a signed tarball under published/.

8. # PR the tarball into your sample-registry repo.
```

### Subscribe to a published pack

```text
1. kb init consumer-kb --tier team --publisher-id did:web:consumer.example

2. # Add the publisher's key to .kb/trust-store.yaml (TOFU on first
   # encounter for team tier; explicit allowlist for enterprise).

3. kb/registry_search/0.1 query="circuit breaker"
   # Lists candidates from the registry.

4. kb/registry_resolve/0.1
     pack_id=my-team.patterns.circuit-breaker
     constraint="^1.0"
   # Returns the best match.

5. kb/subscribe/0.1 pack_id=... version=1.0.0 registry_url=...
   # Fetches, extracts under subscriptions/, runs kb/verify.

6. kb/search/0.1 query="circuit breaker"
   # Now returns hits from the subscribed pack, tagged from:<did>.
```

## 16. Project layout

Top-level repository layout:

| Path | Purpose |
|---|---|
| `README.md` | Short pitch + repo map |
| `OVERVIEW.md` | This document — comprehensive tour |
| `ROADMAP.md` | v1 phased delivery plan (closed 2026-04-14) |
| `ROADMAP-v2.md` | v2 protocol roadmap; index for `rfcs/` |
| `LICENSE.md` | Dual licensing details |
| `LICENSE-APACHE-2.0`, `LICENSE-CC-BY-SA-4.0` | License texts |
| `pyproject.toml` | Python build config |
| `specs/current/` | Authoritative pack + registry specs (v0.1.1 + v0.1) + overview |
| `rfcs/` | Six v2 RFCs (Phase 4-6) |
| `reference/` | Five Python packages (see §3) |
| `tests/` | 134 tests + 4 skipped canaries; adversarial T-suite + D-suite under `tests/adversarial/` |
| `examples/sample-registry/` | Operator template for a git-based registry |
| `examples/skills/kb-distill/` | Single-model team-tier distiller skill |
| `examples/skills/kb-distill-adversarial/` | Dual-model enterprise-tier distiller skill |
| `reports/` | Eight dogfood reports — read in numeric order, then `skill-3a-`, `skill-3b-` |

## 17. Testing

```bash
pytest -q                       # full run; 134 passing + 4 skipped
pytest tests/adversarial -q     # adversarial suites only
pytest tests/test_distiller_family.py -q   # model-family tests

# To unlock the live-LLM canary tests (requires API access):
KBTRANSFER_LLM_TESTS=1 pytest tests/adversarial/test_distiller_skill_canary.py
```

The four skipped tests are documented contracts that need a real
LLM client + harness. Skipping by default keeps CI deterministic;
the contracts light up at first deployment dogfood.

## 18. Status — v1 vs v2

| Track | Status | Where it lives |
|---|---|---|
| v1 reference implementation | ✓ done 2026-04-14 (commit `4e63478`) | `reference/`, `tests/`, `reports/01-06` |
| v2 RFC track (Phase 4-6 planning) | ✓ done 2026-04-15 (commit `085039f`) | `ROADMAP-v2.md`, `rfcs/` |
| Distiller skill 3.a single-model | ✓ done 2026-04-15 (commit `fc75745`) | `examples/skills/kb-distill/` |
| Distiller skill 3.b dual-model | ✓ done 2026-04-15 (commit `833feba`) | `examples/skills/kb-distill-adversarial/` |
| v2 implementation (Phase 4-6 RFCs → code) | not started | will follow `rfcs/` |
| v0.2 spec re-publication | not started | will absorb amendments now in code |

The repo is local-only at the time of writing — no remote push yet.

## 19. Further reading

In rough order of breadth → depth:

1. This file (`OVERVIEW.md`).
2. [`README.md`](./README.md) — short pitch.
3. [`specs/current/autoevolve-packs-overview.md`](./specs/current/autoevolve-packs-overview.md)
   — design rationale + patent-relevant novelty.
4. [`specs/current/autoevolve-spec-v0.1.1.md`](./specs/current/autoevolve-spec-v0.1.1.md)
   — pack format + verification (authoritative).
5. [`specs/current/autoevolve-registry-spec-v0.1.md`](./specs/current/autoevolve-registry-spec-v0.1.md)
   — registry API + federation principles.
6. [`ROADMAP.md`](./ROADMAP.md) + the v1 reports `reports/04-06`.
7. [`ROADMAP-v2.md`](./ROADMAP-v2.md) + the six `rfcs/000N-*.md`
   for v2 plans.
8. The two skill files
   [`examples/skills/kb-distill/SKILL.md`](./examples/skills/kb-distill/SKILL.md)
   and
   [`examples/skills/kb-distill-adversarial/SKILL.md`](./examples/skills/kb-distill-adversarial/SKILL.md)
   for the LLM-driven distillation contracts.
9. [`reports/skill-3a-distiller-single-model.md`](./reports/skill-3a-distiller-single-model.md)
   and
   [`reports/skill-3b-distiller-dual-model.md`](./reports/skill-3b-distiller-dual-model.md)
   for the iteration history of the skills.

## 20. Licensing

- **Code** (`reference/`, `tests/`, `examples/`): Apache License 2.0
  (`LICENSE-APACHE-2.0`).
- **Specs and reports** (`specs/`, `reports/`, `rfcs/`,
  `ROADMAP*.md`, `OVERVIEW.md`): Creative Commons BY-SA 4.0
  (`LICENSE-CC-BY-SA-4.0`).

The split is documented in [`LICENSE.md`](./LICENSE.md). Code is
permissively reusable; specifications stay open and share-alike.

## 21. Attribution

Built on top of:

- The **AutoEvolve Packs** specification (drafted in this repo
  before the implementation began; see `specs/current/`).
- **Andrej Karpathy's LLM-Wiki** pattern
  ([gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).

The patent-relevant novel combinations enabled by this reference
implementation are enumerated in
[`specs/current/autoevolve-packs-overview.md`](./specs/current/autoevolve-packs-overview.md)
under "Patent-relevant novel combinations".
