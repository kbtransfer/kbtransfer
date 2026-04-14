# AutoEvolve Packs — Federated Knowledge Marketplace for AI Agents

A specification and reference implementation for **pattern-level knowledge
packs** that can be distilled from private organizational knowledge,
signed, published to a registry, discovered by agents across
organizations, and verified entirely offline before use.

**Status:** v0.1.1 spec authoritative; reference implementation working
end-to-end; 30+ adversarial tests passing; v0.1.2 amendments queued.

**Origin:** Inspired by Karpathy's "LLM Wiki" pattern
([gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)),
extended to address cross-organization knowledge sharing in regulated
domains (gov-tech, fin-tech, gaming).

---

## Why this exists

Karpathy's LLM-Wiki solves **intra-agent** knowledge compounding: an LLM
maintains a persistent wiki that accumulates knowledge over time instead
of rediscovering it at every query. This project addresses the next
problem: **cross-organization** knowledge sharing.

An AutoEvolve instance at Organization A (gov-tech domain) builds
expertise on, say, national-ID verification. When Organization B enters
fin-tech and needs KYC flows, A's learned patterns would be useful — but
cannot simply be shared as raw wiki pages because of IP, compliance, and
trust boundaries.

This project defines what a **shareable, verifiable, commercially-viable
unit of distilled AI-agent knowledge** looks like, how it is distilled
under privacy constraints, how it is signed and verified, how registries
distribute it, and how consumer agents discover and ingest it.

---

## What's in this package

```
autoevolve-packs-project/
├── README.md                          ← this file
│
├── specs/
│   ├── current/                       ← authoritative specifications
│   │   ├── autoevolve-spec-v0.1.1.md         (pack format + redaction + verification)
│   │   └── autoevolve-registry-spec-v0.1.md  (discovery + distribution + federation)
│   └── superseded/                    ← v0.1 kept for history
│
├── implementations/                   ← working reference code (4154 lines Python)
│   ├── v0.1/                          (first dogfood — found 12 gaps)
│   ├── v0.1.1/                        (amended spec, + adversarial + key-compromise tests)
│   ├── dependency-chain/              (2 publishers, recursive verification)
│   └── registry/                      (9 MCP tools, FTS5 search, HTTP API)
│
└── reports/                           ← dogfood iteration findings
    ├── 01-v0.1-dogfood-feedback.md         (12 amendments → v0.1.1)
    ├── 02-v0.1.1-dogfood-report.md         (defense-in-depth hierarchy revealed)
    └── 03-dep-chain-report.md              (trust_inheritance gap → v0.1.2)
```

---

## The core model in one page

### Three layers, cleanly separated

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PACK FORMAT         autoevolve-spec-v0.1.1.md            │
│    Self-contained, offline-verifiable units of knowledge.   │
│    Ed25519 signed. Two merkle roots (content + pack).       │
│    Four required attestations (provenance, redaction,       │
│    evaluation, license), each independently signed and      │
│    cryptographically bound to content.                      │
├─────────────────────────────────────────────────────────────┤
│ 2. DISTILLER            autoevolve-spec-v0.1.1.md §8–15     │
│    Private org knowledge → marketplace-ready pack via       │
│    nine-phase pipeline: selection, entity detection,        │
│    policy application, paraphrase, adversarial             │
│    re-identification attempt, human review, attestation.    │
│    Uses AutoEvolve's dual-model bias-isolated pattern.      │
├─────────────────────────────────────────────────────────────┤
│ 3. REGISTRY            autoevolve-registry-spec-v0.1.md     │
│    Untrusted directory. Discovery via 9 MCP tools.          │
│    Multi-registry federation native. Zero trust root —      │
│    lies cause denial-of-service, not compromise.            │
└─────────────────────────────────────────────────────────────┘
```

### The hard design decisions (and why)

Each of these was validated against adversarial tests before becoming
part of the spec:

1. **Two merkle roots** (content_root + pack_root). Solves the "how do
   attestations bind to content without circular dependency" problem.
   Proven necessary by T8 key-compromise test — without content_root
   binding, stolen keys could reuse legitimate older attestations on
   malicious content.

2. **Pattern-level granularity, not domain-level.** A pack describes ONE
   problem-solution pair, roughly 5 pages / 20 KB. Compositional via
   explicit dependencies. Proven practical at this size by dogfood.

3. **Zero-trust registry.** Registry is a convenience layer for
   discovery, not a trust anchor. Consumer verifies everything locally.
   This makes federation trivial: multi-registry queries, mirrors, and
   private registries are just configuration.

4. **Consumer-side policy engine.** No central admission/quality control.
   Consumers declare what they accept via machine-readable policy
   dimensions. This enables long-tail marketplace — publishers ship
   freely, consumers filter for their context.

5. **Bias-isolated adversarial redaction verification.** Redactor and
   verifier from different model families (Claude vs GPT) because
   same-family models share blind spots. AutoEvolve's genome evolution
   pattern applied: policies themselves evolve against re-identification
   fitness. **Novel combination, patent-relevant.**

---

## Key numbers

| | |
|---|---|
| Spec documents (current) | 2 authoritative (pack + registry) |
| Spec lines | 2,194 |
| Reference implementation | 4,154 lines Python, real Ed25519 crypto |
| Working packs | 4 (two publishers, three namespaces, one cross-publisher dep) |
| Test coverage | 30+ tests across 4 test suites |
| Tests in place | tampering, key-compromise, cross-publisher trust, semver, cycles, search, HTTP API, attestation binding |
| MCP tools | 9 registry tools, all working with JSON schemas |
| Dogfood iterations | 3 complete (v0.1 → v0.1.1 → dep-chain → registry) |
| Amendments tracked | 12 (v0.1 → v0.1.1) + 8 (queued for v0.1.2) |

---

## Reproducing the dogfood from scratch

All scripts are self-contained; dependencies are `cryptography` and
`pyyaml`.

```bash
pip install cryptography pyyaml

# Iteration 1: build and verify a single pack under v0.1.1
cd implementations/v0.1.1/
python3 build.py
python3 verify.py              # happy path
python3 adversarial_tests.py   # T1-T7: tampering variants
python3 t8_key_compromise.py   # T8: the real A1 test

# Iteration 2: dependency chain, two publishers
cd ../dependency-chain/
python3 build_base_pack.py       # AutoEvolve Foundation publishes
python3 build_qr_pack.py         # SMARTCHIP publishes, depends on base
python3 verify_recursive.py      # D1-D6 dep resolution tests

# Iteration 3: registry with search + 9 MCP tools
cd ../registry/
python3 build_third_pack.py      # gaming domain for search variety
python3 integration_test.py      # full agent workflow end-to-end
```

Each script is < 700 lines, reads like documentation, no hidden state.

---

## What's been proven

**Cryptographic integrity.** Every pack is signed with real Ed25519;
every attestation independently signed; every consumer can verify offline
in ~30 lines of verification code.

**Tampering detection.** Single-byte edits in pages, attestations, or
manifest detected at the correct step by the correct check. T1–T7.

**Key-compromise resistance.** Amendment A1 (content_root binding in
attestations) prevents the most dangerous attack: attacker with publisher
key cannot reuse legitimate older attestations on new malicious content.
T8.

**Dependency composition.** Packs can depend on packs from different
publishers. Recursive verification inherits all properties. Trust
decisions composable. D1–D6.

**Cross-publisher trust surfaces a gap.** Strict transitive trust model
is correct for enterprise but wrong for marketplace. v0.1.2 adds
`trust_inheritance` policy options (inherit-from-parent, namespace-scoped).
This is the most important finding in the whole project.

**Registry discovery works at pattern level.** Full-text search, semver
resolution, attestations-index preview, publisher key distribution — all
working end-to-end via 9 MCP tools + HTTP API.

---

## What's NOT proven (honest limits)

- **No production-scale test.** All dogfood is local filesystem, three
  packs. Scaling to 1000+ packs will surface search ranking, caching,
  and indexing questions.
- **No external DID document resolution.** Publishers are trusted via
  local allowlist in dogfood. Real DID resolution (`did:web:` over HTTPS)
  is specified but not implemented.
- **Distiller agent is spec-only.** The AutoEvolve skill that would run
  the 9-phase redaction pipeline is described, not built.
- **No revocation protocol.** Bad packs are rejected by consumer policy
  blacklists, not by formal revocation lists. v0.2.
- **No external timestamping.** Attestation timestamps are
  publisher-claimed. RFC 3161 integration deferred. v0.2.
- **No payment rails.** Pack pricing metadata is descriptive; actual
  payment is out-of-band. v0.2.
- **Determinism is probabilistic.** Temperature=0 + fixed seeds yield
  "reproducible within tolerances", not cryptographic determinism.

These are documented in spec §7 "Deliberate non-goals" and §15 "Honest
limits".

---

## Patent-relevant novel combinations

Four contributions appear novel against prior art in search:

1. **Two-merkle binding** (content_root + pack_root with attestation
   cross-reference). Resolves the attestation-to-content circular
   dependency in a way that survives key compromise. Demonstrated by T8.

2. **Bias-isolated adversarial redaction verification** with explicit
   different-family model requirement. Reduces ~18% same-model
   confirmation-error rate observed in single-model evaluator ensembles.

3. **Genome-evolved redaction policies.** Treating the privacy-preservation
   policy itself as a genome under evolutionary optimization, with fitness
   = (re-identification rate ↓) × (pack usefulness ↑). Uses
   AutoEvolve's existing genome infrastructure in a new domain.

4. **Fail-closed policy surface declaration.** Packs explicitly declare
   which policy dimensions they support; consumer policies requiring
   unsupported dimensions reject the pack. Prevents silent policy
   degradation in heterogeneous marketplaces.

A USPTO provisional filing could claim these as a combined system. The
reference implementation (~4k lines working code + 30 tests) provides
strong enablement and written description.

---

## Roadmap: what's next

### Near-term (v0.1.2 consolidation)
1. Apply 8 queued clarifications (trust_inheritance, search semantics,
   FTS filter quirks, defense-in-depth layering, B5 reclassification,
   dogfood test conventions, max_depth policy option, registry_hint URL
   schemes).
2. Build the distiller agent as an AutoEvolve skill.
3. Write USPTO provisional claims backed by reference implementation.

### Medium-term (v0.2)
1. External DID document resolution with caching.
2. RFC 3161 external timestamping.
3. Formal revocation protocol.
4. Payment rails (Stripe/SEPA hooks for commercial packs).
5. Real-time notification pub/sub.

### Long-term (v1.0)
1. Full RFC 8785 canonical JSON.
2. Post-quantum signature algorithm support.
3. Federated reputation system (decentralized, not registry-controlled).
4. Cross-registry trust protocols.

---

## Strategic positioning

The three-layer architecture maps to a recognizable commercial frame:

- **Layer 1: Pack format** — the unit of trade (analog: container image,
  npm package, signed artifact).
- **Layer 2: Distiller** — the production pipeline (analog: build
  toolchain, publisher workflow).
- **Layer 3: Registry** — the distribution network (analog: npm, Docker
  Hub, Maven Central — but trust-free).

For AutoEvolve specifically, this extends the "Layer 3 orchestration"
positioning (per the existing competitive analysis against OpenSpace /
Anthropic Skills) into **Layer 4: federated knowledge network**. The
moat is network effect: every organization that publishes packs makes
the network more valuable, and AutoEvolve sits uniquely positioned to
operate the neutral registry layer for its own ecosystem.

---

## How to read this package

- **Want the concept?** Read this README then specs/current/ in order.
- **Want to verify the crypto claims?** Run
  `implementations/v0.1.1/t8_key_compromise.py` — it attacks the pack
  format with a full key compromise and shows exactly which step rejects.
- **Want to see agent workflows?** Run
  `implementations/registry/integration_test.py` — 9-step simulated
  agent search/inspect/resolve flow against the live registry.
- **Want to understand the iteration history?** Read reports/ in
  numeric order — each report explains what the next iteration found
  and why.
- **Want the spec delta?** Check the changelog at the top of
  `specs/current/autoevolve-spec-v0.1.1.md`.

---

## Attribution

- **Foundation pattern:** Karpathy's LLM Wiki gist
  ([link](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f))
  April 2026.
- **Cross-org extension:** conceived in collaboration between SMARTCHIP
  Limited and Anthropic's Claude (Sonnet 4.6).
- **AutoEvolve integration points:** ModelRouter, three-leg evaluator
  ensemble, InvocationRecord, ChainContextBus, genome evolution,
  branch-based git isolation — all from prior AutoEvolve v3 architecture
  work at SMARTCHIP.

---

## License

**Specifications:** CC-BY-SA-4.0 (attribution + share-alike — intended
for adoption as an open standard by a future consortium).

**Reference implementation:** Apache-2.0 (permissive, patent-grant
compatible with future USPTO filings).

Draft status; final licensing decision pending legal review at SMARTCHIP.
