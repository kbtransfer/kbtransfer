# AutoEvolve Pack & Redaction Specification v0.1.1

**Status:** Draft, consolidated from v0.1
**Supersedes:** `autoevolve-pack-spec-v0.1.md`, `autoevolve-redaction-spec-v0.1.md`
**Reference implementation:** `build.py` + `verify.py` (pack-dogfood/)
**Authoritative.** If this document conflicts with prior drafts, this wins.

---

## Changelog from v0.1

All 12 amendments from dogfood feedback applied:

| # | Severity | Amendment |
|---|---|---|
| A1 | high | Attestations now bind to content via `content_root` field (§5.3) |
| A2 | medium | Removed `lock_hash` from manifest (redundant with publisher signature) |
| A3 | high | Trust bootstrap model defined: allowlist default, TOFU opt-in (§6.3) |
| A5 | medium | Signatures now envelope format with `algorithm` + `key_id` + `value` (§5.2) |
| B1 | low | Canonical JSON form specified precisely (Appendix A) |
| B2 | low | Signature scope explicit: canonical form minus `signature` field |
| B3 | low | pack.lock inclusion rule: all files except pack.lock and signatures/** |
| B4 | low | Asset types in pages/ bounded to md, svg, png, jpg, json, yaml |
| B5 | low | License source of truth: attestations/license.json wins on mismatch |
| C1 | low | `residual_risk_notes` promoted to required in redaction attestation |
| C2 | low | `canonical_url` optional field added to manifest |
| C3 | low | Dependencies extended with optional `registry_hint` |

**Known limits carried to v0.2:**
- **A4** — No external timestamp authority; attestation timestamps publisher-claimed.
- Ontology resolution still per-pack manual via crosswalk.
- No revocation protocol for bad packs (consumer policy-based rejection only).

---

# Part I · Pack Format

## 1. Design principles

Three non-negotiable constraints drive every field in this spec:

1. **Self-contained verifiability.** A consumer must be able to evaluate a
   pack's trustworthiness offline, without contacting the registry or the
   publisher. Everything needed for that decision lives inside the pack and
   is cryptographically bound to it.

2. **Composable at pattern granularity.** A pack describes *one*
   problem-solution pair. Large domains are assembled from many packs via
   explicit dependencies, not bundled into monoliths. This is what makes the
   marketplace long-tail.

3. **Machine-readable policy surface.** Consumers run their own policy
   engines. The pack exposes structured attestations (redaction level, data
   residency, license class, evaluation scores) so policies like "only accept
   packs with redaction_level ≥ strict and license ∈ {MIT, Apache-2.0,
   commercial-with-warranty}" are evaluable without human review.

## 2. Directory layout

A pack is a directory (tar/zip for transport) with this structure:

```
sanctions-screening-basic-2.3.1/
├── pack.manifest.yaml           # metadata, listed in pack.lock
├── pack.lock                    # content hashes + two merkle roots; signed
├── README.md                    # human-facing overview
├── pages/                       # content (assets permitted: see below)
│   ├── pattern.md               # core pattern page (required)
│   ├── decision-log.md
│   ├── test-cases.md
│   ├── failure-modes.md
│   ├── crosswalk.md
│   └── diagrams/
│       └── flow.svg             # optional asset
├── attestations/                # machine-readable publisher claims
│   ├── provenance.json
│   ├── redaction.json
│   ├── evaluation.json
│   └── license.json
└── signatures/
    ├── publisher.sig            # signature over pack.lock pack_root
    └── publisher.pubkey         # raw public key bytes
```

**Permitted asset types in pages/** *(amendment B4)*:

| Extension | MIME | Purpose |
|---|---|---|
| `.md` | text/markdown | Primary content (required — at least one) |
| `.svg` | image/svg+xml | Diagrams, flowcharts |
| `.png`, `.jpg` | image/png, image/jpeg | Raster images, screenshots |
| `.json` | application/json | Test fixtures, structured data |
| `.yaml`, `.yml` | application/yaml | Configuration examples |

All assets appear in `pack.lock`. Anything else is rejected at verification.

**Why two merkle roots in pack.lock** *(amendment A1)*: attestations need to bind
to the content they attest to, but attestations themselves are part of the pack.
A single merkle over everything would create a circular dependency (attestation
contains merkle → merkle depends on attestation). Splitting into `content_root`
(pages + manifest + README) and `pack_root` (everything including attestations)
breaks the cycle: attestations bind to `content_root`; publisher signature
covers `pack_root`; both roots appear in `pack.lock`.

## 3. `pack.manifest.yaml` — annotated

```yaml
# ─── Identity ────────────────────────────────────────────────────────────
spec_version: "autoevolve-pack/0.1.1"
pack_id: "sanctions-screening-basic"
version: "2.3.1"                          # semver, breaking = major
namespace: "fintech.compliance"
publisher:
  id: "did:web:smartchip.ie"
  display_name: "SMARTCHIP Limited"
  contact: "packs@smartchip.ie"

# Optional: direct fetch URL for this specific version (amendment C2)
canonical_url: "https://smartchip.ie/packs/sanctions-screening-basic-2.3.1.tar"

# ─── Content summary ─────────────────────────────────────────────────────
title: "Sanctions Screening — Basic Pattern"
summary: >
  Soft-match sanctions screening with dual-list reconciliation, manual review
  queue, and audit trail. Suitable for tier-2 retail banking.
problem_statement: "How to screen counterparties against sanctions lists with
  acceptable false-positive rate at onboarding time."
applicability:
  domains: ["fintech/compliance", "regtech"]
  jurisdictions: ["EU", "UK", "US-lite"]
  scale: "10k-1M screenings/day"
  not_for: ["real-time payment screening", "crypto compliance"]

# ─── Structure ───────────────────────────────────────────────────────────
# NOTE: lock_hash REMOVED (amendment A2). Binding comes via publisher signature
# over pack.lock. Manifest is itself listed in pack.lock.
page_count: 5
total_size_bytes: 47829

# ─── Dependencies (amendment C3: optional registry_hint) ─────────────────
dependencies:
  - pack_id: "base.identity-verification"
    version: "^1.2.0"
    scope: "references"                   # references | extends | contradicts
    registry_hint: "https://registry.autoevolve.io"   # optional
  - pack_id: "regulatory.eu-aml-directive"
    version: "~3.0"
    scope: "references"

# ─── Crosswalk (semantic bridge) ─────────────────────────────────────────
crosswalk:
  ontologies:
    - name: "fibo"
      version: "2024-Q3"
      mappings:
        "our:screening-hit": "fibo:SanctionsMatch"
  equivalents:
    - "bankcorp.compliance.ofac-screening@2.x :: our:screening-hit == their:hit"

# ─── License (machine-readable summary) ──────────────────────────────────
# NOTE: attestations/license.json is the source of truth (amendment B5).
# This block is a convenience summary. On mismatch, pack is REJECTED.
license:
  spdx: "LicenseRef-smartchip-commercial-v1"
  class: "commercial-with-warranty"
  redistribution: false
  derivative_works: "permitted-private"

# ─── Marketplace metadata ────────────────────────────────────────────────
marketplace:
  sku: "SC-FIN-SANCT-BASIC-001"
  pricing_model: "per-seat-annual"
  price_hint_eur: 2400
  trial: { allowed: true, duration_days: 14, feature_mask: "pages-only" }
  support_tier: "business-hours"
  sla_ref: "https://smartchip.ie/sla/pack-v1.pdf"

# ─── Attestations index ──────────────────────────────────────────────────
attestations:
  provenance: "attestations/provenance.json"
  redaction:  "attestations/redaction.json"
  evaluation: "attestations/evaluation.json"
  license:    "attestations/license.json"

# ─── Supported policy dimensions ─────────────────────────────────────────
policy_surface:
  - "redaction_level"
  - "data_residency"
  - "license_class"
  - "evaluation_score"
  - "source_count"
  - "publisher_identity"
  - "jurisdiction_coverage"
```

## 4. `pack.lock` — content integrity

```
# pack.lock
# autoevolve-pack/0.1.1
# Canonical: sorted by path, LF line endings, no trailing whitespace

README.md                      sha256:a1b2c3...
pack.manifest.yaml             sha256:d4e5f6...
pages/pattern.md               sha256:...
pages/decision-log.md          sha256:...
pages/test-cases.md            sha256:...
pages/failure-modes.md         sha256:...
pages/crosswalk.md             sha256:...
pages/diagrams/flow.svg        sha256:...
attestations/provenance.json   sha256:...
attestations/redaction.json    sha256:...
attestations/evaluation.json   sha256:...
attestations/license.json      sha256:...

content_root: sha256:7c4a...e29f
pack_root:    sha256:3f2a...b91c
```

**File inclusion rule** *(amendment B3)*: `pack.lock` covers every file under
the pack root recursively, EXCEPT:
- `pack.lock` itself
- Anything under `signatures/`

**Merkle computation** *(deterministic)*:

```
content_files = {all files matching {README.md, pack.manifest.yaml, pages/**}}
pack_files    = content_files ∪ {attestations/**}

For each set, produce a canonical byte string by concatenating
  f"{relative_path}:{sha256_hex}\n"
for each file in ascending UTF-8 byte order of path.

content_root = sha256(canonical string of content_files)
pack_root    = sha256(canonical string of pack_files)
```

Both roots appear in `pack.lock` as shown above.

**Publisher signature** *(amendment A5, B2)*: `signatures/publisher.sig` is a
raw Ed25519 signature over the byte string:

```
"autoevolve-pack/0.1.1\n" || pack_root_hex_ascii
```

where `pack_root_hex_ascii` is the 64-character lowercase hex from `pack.lock`.

## 5. Attestations

### 5.1 Structure

Each attestation is a separate JSON file under `attestations/`. All
attestations share a common envelope:

```json
{
  "spec": "autoevolve-attestation/{kind}/0.1.1",
  "pack": "{pack_id}@{version}",
  "content_root": "sha256:7c4a...e29f",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "2026-04-10T14:32:08Z",

  // ... kind-specific body ...

  "signature": {
    "algorithm": "ed25519",
    "key_id": "smartchip-2026Q2",
    "value": "hex..."
  }
}
```

**Binding to content** *(amendment A1)*: every attestation's `content_root`
field MUST equal the `content_root` recorded in `pack.lock`. Consumer
rejects any attestation whose `content_root` does not match. This makes
attestations non-portable across pack versions and binds them to specific
content.

### 5.2 Signature envelope *(amendment A5)*

```json
"signature": {
  "algorithm": "ed25519",           // ed25519 only in v0.1.1
  "key_id": "smartchip-2026Q2",     // publisher's key registry identifier
  "value": "7f3a...ef92"            // lowercase hex, 128 chars for ed25519
}
```

The signature value is computed over the **canonical JSON serialization**
(Appendix A) of the attestation **with the `signature` field removed**
*(amendment B2)*.

The `key_id` allows publishers to rotate keys without invalidating old
attestations. Consumer resolves `key_id` → public key via the publisher's
key registry (see §6.3 on trust bootstrap).

### 5.3 Attestation kinds

#### `provenance.json`
```json
{
  "spec": "autoevolve-attestation/provenance/0.1.1",
  "pack": "sanctions-screening-basic@2.3.1",
  "content_root": "sha256:...",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "2026-04-10T14:32:08Z",
  "derived_from": {
    "source_documents": 47,
    "source_types": ["regulatory-text", "client-case-study", "internal-decision"],
    "autoevolve_sessions": 312,
    "session_composite_score_mean": 0.89,
    "session_composite_score_p10": 0.71,
    "evolution_genome_version": "v6.2"
  },
  "raw_source_manifest_hash": "sha256:...",
  "build_environment": "autoevolve-v3.1.4",
  "signature": { "algorithm": "ed25519", "key_id": "...", "value": "..." }
}
```

#### `redaction.json` — `residual_risk_notes` now required *(amendment C1)*
```json
{
  "spec": "autoevolve-attestation/redaction/0.1.1",
  "pack": "sanctions-screening-basic@2.3.1",
  "content_root": "sha256:...",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "2026-04-10T14:32:08Z",
  "redaction_level": "strict",
  "policy_applied": "smartchip-redaction-policy-v2",
  "policy_version": "2.1.0",
  "policy_hash": "sha256:...",
  "categories_redacted": [ ... ],
  "categories_preserved": [ ... ],
  "automated_checks": { ... },
  "adversarial_verification": {
    "verifier_model": "gpt-4.1-2026-02",
    "targets_tested": 4,
    "targets_passed": 4,
    "max_reidentification_confidence": 0.07,
    "threshold": 0.10
  },
  "human_review": { "reviewers": [ ... ] },
  "residual_risk_notes": [
    "REQUIRED field. At least one entry. Publisher must articulate what",
    "this redaction does NOT protect against. Empty array is not permitted."
  ],
  "signature": { ... }
}
```

#### `evaluation.json`
```json
{
  "spec": "autoevolve-attestation/evaluation/0.1.1",
  "pack": "sanctions-screening-basic@2.3.1",
  "content_root": "sha256:...",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "...",
  "evaluators": [ { ... } ],
  "test_cases": { ... },
  "third_party_review": null,
  "signature": { ... }
}
```

#### `license.json` — source of truth *(amendment B5)*
```json
{
  "spec": "autoevolve-attestation/license/0.1.1",
  "pack": "sanctions-screening-basic@2.3.1",
  "content_root": "sha256:...",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "...",
  "license_spdx": "LicenseRef-smartchip-commercial-v1",
  "license_text_hash": "sha256:...",
  "license_text_url": "https://smartchip.ie/licenses/commercial-v1.txt",
  "grants": ["internal-use", "private-derivatives"],
  "restrictions": ["no-redistribution", "no-public-derivatives"],
  "warranty": "limited-12-months",
  "signature": { ... }
}
```

**On mismatch with manifest.license block**: pack is REJECTED. `license.json`
is authoritative.

## 6. Verification procedure

### 6.1 Flow

```
  ┌────────────┐  ┌───────────┐  ┌──────────────┐  ┌──────────────┐
  │ 1. Fetch   │→ │ 2. Verify │→ │ 3. Verify    │→ │ 4. Verify    │
  │    pack    │  │    content│  │    attestations │   policy     │
  └────────────┘  │    root   │  │    bindings  │  │    (local)   │
                  └───────────┘  └──────────────┘  └──────────────┘
                        ↓               ↓                  ↓
                  ┌───────────┐  ┌──────────────┐  ┌──────────────┐
                  │ 5. Verify │→ │ 6. Resolve   │→ │ 7. Ingest    │
                  │    pub sig│  │    deps      │  │   + Record   │
                  └───────────┘  └──────────────┘  └──────────────┘
```

### 6.2 Step detail

1. **Fetch.** Consumer obtains pack tarball. Source is untrusted.

2. **Verify content_root.** Recompute `content_root` from files (§4 algorithm).
   Compare to the value stored in `pack.lock`. Reject on mismatch.

3. **Verify attestation bindings.** For each file under `attestations/`:
   - Parse JSON
   - Check `content_root` field equals recomputed `content_root`
   - Check `spec` version is supported
   - Resolve `signature.key_id` to public key bytes (§6.3)
   - Verify signature over canonical JSON of attestation minus `signature` field

4. **Verify policy.** Evaluate consumer policy against attestation fields.
   All `policy_surface` dimensions the policy requires must be present in
   the pack's declared surface. Fail-closed on any missing dimension.

5. **Verify publisher signature over pack_root.**
   - Recompute `pack_root` from all files in `pack.lock` (§4 algorithm)
   - Compare to the value stored in `pack.lock`
   - Verify `signatures/publisher.sig` against
     `"autoevolve-pack/0.1.1\n" || pack_root_hex` using the publisher's
     current signing key (resolved per §6.3)

6. **Resolve dependencies.** For each entry in `manifest.dependencies`:
   - Apply version constraint against known available versions
   - If `registry_hint` provided, consult that registry first
   - Recursively apply this verification procedure to resolved dependency
   - Inherit trust: if dep publisher is not in consumer allowlist, check
     policy for `trust_inheritance` rule

7. **Ingest + record.**
   - Import pack pages under `imported/{pack_id}/{version}/` in local wiki
   - Append crosswalk entries to ontology index
   - Write `InvocationRecord` entry with pack_id, version, content_root,
     policy verdict, attestation digest
   - Append log entry

### 6.3 Trust bootstrap *(amendment A3)*

Consumer resolves publisher keys via one of three models, declared in
consumer policy:

**Model A — Allowlist (DEFAULT).**
```yaml
trust_model: allowlist
trusted_publishers:
  - id: "did:web:smartchip.ie"
    keys:
      - key_id: "smartchip-2026Q2"
        ed25519_pubkey: "5e7508...32b1"
        valid_from: "2026-04-01"
        valid_until: "2026-09-30"
  - id: "did:web:bankcorp.example"
    keys:
      - key_id: "bankcorp-prod-v1"
        ed25519_pubkey: "..."
```
Unknown publisher → rejection. No network calls. Fully offline.

**Model B — TOFU (Trust On First Use), opt-in.**
```yaml
trust_model: tofu
tofu_store: "~/.autoevolve/trusted_keys.yaml"
```
First encounter with a publisher: record their key. Subsequent key change:
require explicit user confirmation. Suitable for individual developers;
risky for enterprise.

**Model C — Registry-assisted (v0.2).**
Registry publishes signed publisher directory. Consumer trusts registry's
meta-key (bootstrapped out-of-band). Deferred to v0.2 — requires registry
spec work (Q2).

**DID resolution.** `did:web:*` identifiers MAY be resolved online at
allowlist-provisioning time (fetch `https://{domain}/.well-known/did.json`,
extract keys), but MUST NOT be resolved per-verification. Offline
verifiability is preserved by caching resolved keys in the allowlist.

## 7. Deliberate non-goals

Explicitly out of scope for v0.1.1:

- **Payload encryption.** Packs are signed, not encrypted. Confidentiality
  is controlled by distribution channel, not by the pack format.
- **Revocation protocol.** Bad packs are rejected via consumer policy
  (e.g., blacklist rule). Formal revocation lists deferred to v0.2.
- **Payment rails.** Marketplace pricing metadata is descriptive only.
  Payment is out-of-band in v0.1.1.
- **Automatic ontology resolution.** Crosswalk is per-pack manual.
- **Write-back protocol.** Packs are read-only after publishing. Updates =
  new version. Feedback to publisher is out-of-band.
- **External timestamping** (amendment A4 / known limit). Attestation
  timestamps are publisher-claimed; no RFC 3161 binding in v0.1.1.

---

# Part II · Redaction Policy & Distiller

## 8. Design principles

1. **Policy as code, not prose.** A redaction policy is a YAML document
   with deterministic semantics. Two auditors reading the same policy
   reach the same conclusions.

2. **Adversarial verification is mandatory.** The distiller uses
   AutoEvolve's dual-model bias-isolated pattern: one model redacts, a
   structurally isolated model acts as adversarial verifier trying to
   re-identify redacted entities.

3. **Honest about limits.** Automated redaction cannot guarantee zero
   leakage. The spec acknowledges residual risk explicitly and requires
   human review above `standard` level. `residual_risk_notes` is mandatory
   in every redaction attestation (amendment C1).

4. **Deterministic where possible.** Same inputs + same policy + same
   model versions + same seed = byte-identical output within published
   tolerances.

5. **Consistent pseudonymization.** If "Acme Corp" is redacted to
   `<CLIENT_01>` on page 3, every other mention in the pack maps to the
   same placeholder.

## 9. Redaction levels

Four discrete levels. Every redaction attestation declares exactly one.
Level semantics are cumulative — each level includes all transformations
of levels below it.

### 9.1 `minimal`
**Redacts:** person names, email addresses, phone numbers, physical
addresses, government IDs, credit card numbers, biometric identifiers.
**Preserves:** company names, monetary amounts, dates, internal system
names, quotes.
**Human review:** not required.
**Typical use:** open-source pattern pack derived mostly from public
sources.

### 9.2 `standard`
**Additionally redacts:** client/customer organization names, vendor
names, internal system names and codenames, internal project identifiers,
exact monetary amounts (→ order-of-magnitude ranges), employee identifiers
and roles at organization-identifying specificity.
**Preserves:** industry sector, generic roles, date ranges at quarter
granularity, jurisdictions at country level, public API/protocol names.
**Human review:** one designated reviewer, identity recorded in
attestation.

### 9.3 `strict`
**Additionally redacts:** direct quotes → paraphrased, dates → quarter/
year, sub-national locations → region/country, team sizes → bands,
project timelines → phase durations. Correlation guard: combinations
that uniquely identify an entity are flagged and generalized.
**Human review:** two independent reviewers.

### 9.4 `paranoid`
**Additionally redacts:** individual cases → aggregates across ≥ 5, exact
counts → bucketed ranges, anything traceable to a single decision-maker
or single time window, differential privacy noise on numeric claims.
**Human review:** two reviewers + legal counsel sign-off.

## 10. Entity taxonomy

Hierarchical, dotted paths. The policy engine operates on these classes.

```
identity/{person, organization, role}
financial/{amount-exact, amount-range, revenue, valuation}
temporal/{date-exact, date-window, duration}
spatial/{address, facility, jurisdiction}
technical/
  internal/{hostname, ip-address, repository, service-name, codename, database-schema}
  public/{protocol, standard, published-api}          # usually NOT redacted
communication/{direct-quote, paraphrased-quote}
regulatory/{statute-reference, internal-legal-opinion} # statute usually NOT redacted
```

Each class has default operations at each level. Policies override.

## 11. Redaction operations

| Op | Semantics |
|----|-----------|
| `remove` | Delete span; adjust surrounding text for grammaticality |
| `placeholder` | Replace with stable pseudonym consistent across pack |
| `generalize` | Replace with broader category |
| `paraphrase` | Preserve semantic content, destroy exact phrasing |
| `aggregate` | Replace instance with aggregate across ≥ N |
| `hash` | Replace with stable hash; consistent pseudonym |

**Consistency requirement.** `placeholder` and `hash` use the same mapping
table across the entire pack. The mapping table is NOT shipped — it stays
in the publisher's private build environment.

## 12. Policy DSL

```yaml
policy_id: "smartchip-redaction-policy-v2"
policy_version: "2.1.0"
base_level: "strict"

rules:
  - class: "identity.person.employee"
    operation: "remove"
  - class: "regulatory.statute-reference"
    operation: "preserve"
  - class: "financial.amount-exact"
    operation: "generalize"
    params:
      buckets: ["<€100k", "€100k-€1M", "€1M-€10M", "€10M-€100M", ">€100M"]
  - class: "communication.direct-quote"
    operation: "paraphrase"
    params:
      preserve_semantic_similarity_min: 0.75

pseudonym_scope: "pack"           # pack | publisher | global

correlation_guard:
  k_anonymity_target: 5
  flag_if_unique_identification_prob: 0.20

human_review:
  required: true
  min_reviewers: 2
  reviewer_roles: ["compliance-officer", "domain-expert"]

adversarial_targets:
  - "recover any redacted client name with >10% confidence"
  - "identify any employee by role + temporal window"
  - "recover exact monetary amounts within 20%"

determinism:
  redactor_model: "claude-sonnet-4-6@2026-03"
  verifier_model: "gpt-4.1-2026-02"          # MUST differ from redactor
  paraphrase_seed: 42
  temperature: 0
```

Policy hash = sha256 over canonical YAML. Hash appears in every
`redaction.json` attestation, binding the pack to the exact policy version
used.

## 13. Distiller pipeline

Nine phases. Reuses existing AutoEvolve primitives (§14).

1. **Selection** — publisher declares which PRIVATE pages go in, which
   spans are excluded a priori.
2. **Entity detection** — three parallel detectors (regex, NER, LLM
   classifier). Spans agreed by ≥ 2 of 3 auto-classified; spans by only 1
   queued for adversarial verifier.
3. **Entity resolution** — cluster mentions into entities. String
   similarity + LLM co-reference + optional publisher alias list.
4. **Policy application** — operations applied deterministically per class.
5. **Paraphrase pass** — semantic similarity measured by third model
   (distinct from redactor and verifier). Must exceed policy threshold.
6. **Consistency check** — cross-page references still resolve.
7. **Adversarial verification** — isolated model attempts re-identification
   against each `adversarial_target`. Failure returns to §4 with additional
   generalization; three failures → human review.
8. **Human review gate** — if policy requires. Reviewer identity logged.
9. **Attestation build** — sign and bundle all four attestations.

## 14. AutoEvolve integration

| AutoEvolve primitive | Role in distiller |
|---|---|
| `ModelRouter` | Routes redactor, verifier, paraphraser to distinct models |
| Three-leg evaluator ensemble | Semantic similarity in paraphrase pass |
| `InvocationRecord` | Provenance attestation backing |
| `ChainContextBus` | Carries entity resolution table through phases |
| Genome evolution | Distiller policies ARE genomes; adversarial re-ID rate + pack usefulness form fitness function |
| Branch-based git isolation | Each distillation in isolated branch |

The genome row is patent-relevant: **redaction policies evolve via
bias-isolated adversarial fitness evaluation**. This combination is novel.

## 15. Honest limits

What this spec does NOT claim:

- **No guarantee against motivated re-identification.** Reduces probability;
  does not eliminate.
- **Aggregate queries leak.** Multi-pack composition can defeat pack-level
  privacy via differential attacks.
- **LLM paraphrasing is imperfect.** Semantic similarity catches most
  quote leakage; stylometric features survive.
- **Ontology poisoning risk.** Malicious crosswalk entries can mislead
  composition; consumer policy should require review of crosswalk from
  untrusted publishers.
- **Determinism is probabilistic.** Temperature=0 + fixed seeds yield
  "reproducible within published tolerances", not cryptographic determinism.

`residual_risk_notes` in every redaction attestation MUST enumerate the
specific limits that apply to that pack.

---

# Appendices

## Appendix A — Canonical JSON (canonical-2026-04)

For v0.1.1, canonical JSON serialization is defined as:

1. UTF-8 encoding, no BOM
2. Object keys sorted lexicographically by UTF-8 byte order
3. Separators: `,` between elements, `:` between key/value, no whitespace
4. String escapes: `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t`, `\uXXXX` for
   control characters only; other Unicode code points emitted directly
5. Numbers: integers as-is, floats in shortest unambiguous form
6. `NaN`, `+Infinity`, `-Infinity` rejected
7. Arrays preserve order
8. Unicode normalization NOT required in v0.1.1 (v0.2: NFC required)

Python reference:
```python
def canonical_json(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
```

This is **canonical-2026-04**, a subset of RFC 8785. For strict
interoperability v0.2 will commit to full RFC 8785.

## Appendix B — Signature envelope

```json
{
  "algorithm": "ed25519",
  "key_id": "string-identifier",
  "value": "lowercase-hex"
}
```

**Algorithms accepted in v0.1.1:**
- `ed25519` — Ed25519 per RFC 8032. 64-byte signature. 32-byte public key.

Future v0.2 MAY add `ed448`, `secp256k1`. Consumer implementations MAY
accept additional algorithms but MUST support `ed25519`.

**Key resolution.** `key_id` is resolved via the publisher's key registry.
Structure of key registry entry:
```yaml
key_id: "smartchip-2026Q2"
publisher: "did:web:smartchip.ie"
algorithm: "ed25519"
public_key_hex: "5e7508..."
valid_from: "2026-04-01T00:00:00Z"
valid_until: "2026-09-30T23:59:59Z"     # optional
revoked: false
revocation_reason: null
```

## Appendix C — Minimal pack example

A valid pack with the minimum required files:

```
minimal-example-1.0.0/
├── pack.manifest.yaml          # manifest
├── pack.lock                   # generated
├── README.md                   # can be a single sentence
├── pages/
│   └── pattern.md              # at least one .md required
├── attestations/
│   ├── provenance.json
│   ├── redaction.json
│   ├── evaluation.json
│   └── license.json
└── signatures/
    ├── publisher.sig
    └── publisher.pubkey
```

All four attestations are required. `redaction.json` is required even
for packs derived from fully public sources — in that case
`redaction_level: "minimal"` and `residual_risk_notes` enumerates the
public-source risks (e.g., "sources may contain author identification
via stylometric features").

## Appendix D — Reference implementation

`build.py` and `verify.py` in the pack-dogfood/ directory implement this
spec. ~500 lines of Python, depends only on `cryptography` and `pyyaml`.
Both scripts are authoritative tie-breakers: if this document is ambiguous
and the reference implementation is unambiguous, the reference
implementation wins for v0.1.1.

---

*End of spec v0.1.1.*
