# Phase 2 Dogfood Report

**Scope:** pack format + verify + tier-aware distiller + five new
MCP tools + T1-T8 adversarial suite.
**Targets:**
- `kb_pack` (build + verify faithful to spec v0.1.1 §§2-6).
- `kb_distiller` (regex scrubber + tier-aware pipeline).
- `kb/{draft_pack, distill, publish, subscribe, verify}/0.1`.
- Cross-KB round-trip with isolated, read-only subscriptions.
- T1-T8 adversarial suite, T8 load-bearing.
**Status:** 64 / 64 tests passing. Phase 2 functionally complete.

---

## 1. What was built

```
reference/
├── kb_pack/
│   ├── canonical.py      canonical-2026-04 JSON (spec Appendix A)
│   ├── manifest.py       required-field + spec-version validation
│   ├── merkle.py         two-merkle computation (content_root, pack_root)
│   ├── lock.py           pack.lock round-trip (sha256: prefixed)
│   ├── signature.py      Ed25519 envelopes + pack_root signing
│   ├── attestation.py    four attestation kinds, C1 enforced at build
│   ├── build.py          two-phase builder per amendment A1
│   └── verify.py         seven-step §6.2 procedure
├── kb_distiller/
│   ├── scrubber.py       five regex categories, stable pseudonyms
│   └── pipeline.py       tier -> mode mapping + checklist routing
└── kb_mcp_server/
    ├── publisher_context.py  tier.yaml + key-pair resolver
    ├── trust_store.py        TOFU + allowlist resolver bridge
    └── tools/
        ├── draft_pack.py     scaffold drafts/<pack_id>/
        ├── distill.py        run pipeline, persist .distill-report.json
        ├── publish.py        populate atts, seal, tar under published/
        ├── subscribe.py      verify + install under subscriptions/
        └── verify.py         stand-alone re-verification
```

Twelve `kb/*` tools now exposed over stdio. Full Phase 1 surface
unchanged.

## 2. Spec compliance checklist

| Spec reference               | Anchor in code |
|------------------------------|----------------|
| §3 manifest + REQUIRED_FIELDS | `kb_pack.manifest.validate` |
| §4 two-merkle roots          | `kb_pack.merkle.compute_roots` |
| §4 file inclusion rule (B3)  | `_iter_pack_files` exclusions |
| §4 pack.lock format          | `kb_pack.lock.render_lock` |
| §5.1 attestation envelope    | `kb_pack.attestation.build_envelope` |
| §5.2 signature envelope (A5) | `kb_pack.signature.make_envelope` |
| §5.3 content_root binding (A1) | `build.py` injects + `verify.py` S3a |
| §5.3 residual_risk_notes (C1) | `attestation.build_redaction` + `build.py` gate |
| §6.2 seven-step verify       | `kb_pack.verify.verify_pack` |
| Appendix A canonical JSON    | `kb_pack.canonical.canonical_json` |
| Amendment A2 (no lock_hash)  | `manifest.validate` rejects it |
| Amendment B2 (sig scope)     | `signature.sign_attestation` strips before signing |
| Amendment B5 (license SoT)   | `verify.py` S3c manifest/license consistency |

Defense-in-depth per `reports/02` verified empirically by the T1-T8
suite below.

## 3. T1-T8 adversarial results

| # | Attack                                      | Expected | Actual | Verdict |
|---|---------------------------------------------|----------|--------|---------|
| T1 | Tamper page content                        | S2       | S2     | ✓       |
| T2 | Tamper attestation body                    | S2       | S2     | ✓       |
| T3 | Swap attestation with different content_root | S2       | S2     | ✓       |
| T4 | Manifest.license != license.json           | S2 (B5 unreachable via malicious path) | S2 | ✓ |
| T5 | Empty residual_risk_notes                  | S2       | S2     | ✓       |
| T6 | Invalid key_id in envelope (attacker re-signs pack_root) | S3b | S3b | ✓ |
| T7 | Algorithm downgrade to non-ed25519         | S3b      | S3b    | ✓       |
| T8 | **Key compromise + stale attestation reuse** | **S3a (A1)** | **S3a (A1)** | ✓ **load-bearing** |

T1-T5 group: the attacker only modifies bytes. SHA-256 hash checks
catch them at S2 regardless of semantic content. This reproduces the
"hash-in-lock is the dominant defense" finding from the spec v0.1.1
dogfood.

T6-T7 group: the attacker has enough privilege to re-seal pack.lock
and publisher.sig (simulated by re-running the lock + signature
steps in the test after mutating the envelope). Now S2 passes and
the semantic checks at S3b fire — proving the envelope validation
is load-bearing exactly in the attack model it was designed for.

**T8 is the canonical A1 test.** The attacker holds the publisher's
signing key and wants to ship new malicious content while reusing a
legitimate older attestation. After building pack v1 and stealing
its redaction attestation, the attacker swaps that attestation into
a pack v2 with different (malicious) content, re-locks and re-signs
pack_root. The verifier fires S3a with the message
`attestation redaction content_root does not match pack.lock`,
rejecting the substitution. Without amendment A1's `content_root`
field on attestations, this attack would succeed silently.

## 4. Round-trip dogfood (publisher -> consumer)

`tests/test_mcp_pack_lifecycle.py::test_subscribe_verifies_and_installs_pack`
scripts the full flow two independent KBs exercise:

1. Publisher KB (`did:web:pub.example`, individual tier) runs
   `kb/draft_pack/0.1` against two wiki pages; the resulting
   `drafts/example.p/` carries the manifest, README, copied pages,
   and four attestation stubs.
2. `kb/distill/0.1` scrubs `alice@example.com` → `<EMAIL_01>`
   consistently across pages, emits `.distill-report.json`.
3. `kb/publish/0.1` fills in the four attestations (redaction
   consumes the distill report verbatim), runs `build_pack`, and
   tars the result at `published/example.p-0.1.0.tar`. Both merkle
   roots are sha256-prefixed and returned in the tool envelope.
4. Consumer KB (`did:web:cons.example`, also individual) runs
   `kb/subscribe/0.1` against the local tarball path. The pack is
   extracted to a temp area, its publisher key auto-registered in
   `.kb/trust-store.yaml` (TOFU), and the seven-step verify runs
   against a resolver built from the trust store. On success the
   pack lands under
   `subscriptions/did-web-pub.example/example.p/0.1.0/`.
5. Cross-source search: a query for a unique token present both in
   consumer's own wiki and in the newly-subscribed pack returns
   hits tagged `mine` and `from:did-web-pub.example` simultaneously.

## 5. Policy-gated rejection

`test_subscribe_enterprise_without_allowlist_rejects` shows the
tier-dependent posture working: an enterprise consumer with
`trust.tofu_enabled: false` rejects the same pack at
`untrusted_publisher` without ever running verification. Adding the
publisher's key to `.kb/trust-store.yaml` (out-of-band admin step)
would unblock it. This is exactly the intended enterprise onboarding
posture per the locked design decisions.

## 6. Findings

### 6.1 Lock roots must carry the `sha256:` prefix

The first draft stored raw hex in `Lock.content_root` and
`Lock.pack_root`, stripped at parse time. Every cross-artifact
comparison (attestation.content_root vs lock.content_root, for
example) then needed normalization, which the build-vs-verify
roundtrip immediately broke. Switched both roots to the full
`sha256:<hex>` form everywhere they are exposed; signing, which
per spec §4 needs the bare hex, does one `removeprefix` at the
call site.

Recommendation for v0.1.2 spec text: note explicitly that
`content_root` and `pack_root` values persist with the `sha256:`
prefix in every format (`pack.lock`, manifest, attestation) and that
the raw-hex form is only used inside the publisher-signature
payload.

### 6.2 `.distill-report.json` must live outside the pack's merkle

The distill report is a build-time artifact, not a consumer-visible
one. My first pass left it under `drafts/<pack_id>/` alongside
everything else; the tarball excluded it while the signed directory
on disk still held it — silent pack_root drift the verifier caught
at S2 on subscribe. Fix: `kb/publish/0.1` deletes the report before
calling `build_pack`. This is the right long-term boundary too: the
report contains the agent's checklist and may include sensitive
placeholder mappings in future tiers.

### 6.3 macOS symlink handling bit us twice

`/tmp` is `/private/tmp` on macOS; `tmp_path` in pytest is
`/var/folders/...` which resolves to `/private/var/folders/...`.
Mixing resolved and unresolved paths inside a tool handler breaks
`Path.relative_to`. Fixed by resolving both sides of any sandbox
check (`draft_pack._copy_pages`) and by calling `root = root.resolve()`
at the top of `publish.HANDLER`. Consider hoisting this into the
MCP server's dispatch loop for Phase 3.

### 6.4 `signatures/publisher.pubkey` bundling is useful but NOT a trust root

Per spec §4 we ship the publisher's raw Ed25519 public key next to
the signature. The verifier uses it only as an **integrity check**
against the trusted key resolved from `.kb/trust-store.yaml`; a
mismatch at S5 aborts verification without consulting the bundled
bytes as a signing key. Test
`test_verifier_rejects_when_bundled_pubkey_differs` pins this
contract: swapping the bundled pubkey for another valid Ed25519
key is caught at S5.

## 7. Spec amendments queued for v0.1.2

None newly surfaced by Phase 2 beyond the eight already queued from
the three prior dogfood reports. The Phase 2 amendments (A1-C3 from
v0.1 and the eight items from `03-dep-chain-report.md`) are either
already applied (A1, A2, A5, B2, B3, B4, B5, C1, C2, C3) or land in
Phase 3 (trust_inheritance, max_depth, registry_hint URL schemes,
breadcrumb errors, defense-in-depth §5.4 doc).

Minor additions from Phase 2 itself worth recording:

1. **Text clarification (v0.1.2):** roots always persist prefixed in
   external artifacts; bare hex form is strictly for the publisher
   signing payload.
2. **Test-suite requirement (v0.1.2):** dogfood MUST include T8-style
   key-compromise test — already present here.
3. **Build hygiene recommendation:** distillation reports are
   out-of-band of the pack and MUST NOT land inside the merkle.

## 8. What's explicitly NOT proven

- **No git-based registry.** Subscribe accepts only local paths;
  remote fetch is Phase 3.
- **No trust_inheritance.** Individual and team tiers use TOFU;
  enterprise uses strict allowlist. Neither layers namespace-scoped
  or inherit-from-parent modes yet. Cross-publisher dependency tests
  (D1-D6 from the prior dogfood) land in Phase 3.
- **No LLM inference inside the server.** Single-model and
  dual-model distillation modes emit a checklist and persist a
  report. The agent performs the actual paraphrasing and
  cross-entity redaction through `kb/write/0.1` on draft pages.
  This is by design — the server stays deterministic and offline —
  but means a dual-model adversarial verification is not
  automatically enforced by the runtime.
- **No external timestamping.** Still publisher-claimed per spec
  §7 non-goals.

## 9. Cumulative status

| | |
|-|-|
| Code in Phase 2         | +3,200 lines across kb_pack, kb_distiller, kb_mcp_server |
| MCP tools now exposed   | 12 (Phase 1: 7 + Phase 2: 5) |
| Tests                   | **64 / 64** passing |
| Adversarial suite       | T1-T8 ✓ |
| Defense-in-depth layers | All four documented in `reports/02` exercised |
| Commits in Phase 2      | 4 |
| Phase 3 readiness       | Ready — git registry + trust inheritance next |

## 10. Deliverables in this iteration

```
Phase-2/
├── reference/kb_pack/                             (build + verify)
├── reference/kb_distiller/                        (scrubber + pipeline)
├── reference/kb_mcp_server/publisher_context.py
├── reference/kb_mcp_server/trust_store.py
├── reference/kb_mcp_server/tools/draft_pack.py
├── reference/kb_mcp_server/tools/distill.py
├── reference/kb_mcp_server/tools/publish.py
├── reference/kb_mcp_server/tools/subscribe.py
├── reference/kb_mcp_server/tools/verify.py
├── tests/test_pack_core.py                        (11 tests)
├── tests/test_pack_build_verify.py                (4 tests)
├── tests/test_distiller.py                        (6 tests)
├── tests/test_mcp_pack_lifecycle.py               (6 tests)
├── tests/adversarial/test_t1_t8.py                (8 tests — T8 load-bearing)
└── reports/05-phase2-dogfood-report.md            (this file)
```

---

*End of Phase 2 dogfood report. Phase 3 — git-based registry,
trust_inheritance, dependency chain — starts next.*
