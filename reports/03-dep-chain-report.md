# Dependency Chain Test Report

**Targets:** 2 packs in a dependency relationship
- `smartchip.govtech.qr-offline-authorization@1.0.1` (SMARTCHIP)
- `base.crypto.ed25519-signing@1.0.0` (AutoEvolve Foundation — different publisher)

**Result:** 6/6 tests passed. One significant new architectural finding
revealed, documented below.

---

## 1. Setup

Two real packs, two different publishers, two distinct Ed25519 keypairs.
The dependency relationship:

```
smartchip.govtech.qr-offline-authorization@1.0.1
  │  (publisher: did:web:smartchip.ie)
  │
  └── depends on: base.crypto.ed25519-signing@^1.0
                   (publisher: did:web:autoevolve.io)
                   resolved to: 1.0.0
```

Registry simulated by local filesystem at `registry/{pack_id}/{version}/`.
`registry_hint: file:///home/claude/dep-chain-test/registry` in the
manifest dependencies block points to it. In production this would be
`https://registry.autoevolve.io` or similar.

Recursive verifier: ~80 lines on top of v0.1.1 single-pack verifier.
Applies full §6 verification at every depth level.

## 2. Test matrix

| # | Scenario | Outcome | Notes |
|---|---|---|---|
| D1 | Happy path: both packs present, both trusted | ✓ accept | 2 packs verified recursively |
| D2 | Dependency missing from registry | ✓ reject | Error includes registry_hint |
| D3 | Version constraint unsatisfiable (`^1.0` vs `2.0.0` available) | ✓ reject | Semver matching works |
| D4 | Content tampering inside the dependency | ✓ reject at S3a | Defense-in-depth extends into deps |
| D5 | **Dep publisher not in consumer's trust store** | ✓ reject at S3b | **New architectural finding — see §3** |
| D6 | Cycle introduced by editing base.crypto to depend on qr-offline | ✓ reject at S3a | Cycle preempted by content_root check |

## 3. Key finding: trust inheritance policy needed (v0.1.2)

D5 setup: consumer's trust store contains SMARTCHIP's key but NOT
AutoEvolve Foundation's key. Verification:

```
qr-offline@1.0.1 verifies cleanly (SMARTCHIP signed, consumer trusts)
  └── recurses into base.crypto@1.0.0
      └── attestations signed by AutoEvolve Foundation
          ✗ S3b: "untrusted issuer/key_id: did:web:autoevolve.io/..."
          → whole pack graph rejected
```

This is the default behavior implied by v0.1.1's §6.3 trust model: every
pack in the transitive dependency closure must have its publisher in the
consumer's trust store. Strict, safe default.

But real-world marketplaces need more options. Consider:

- **Scenario A (enterprise consumer):** security team pre-vets and
  allowlists a small set of publishers. Any transitive dep from an
  unvetted publisher = rejection. This is the current v0.1.1 behavior
  and is correct for this scenario.

- **Scenario B (developer/SMB consumer):** trusts SMARTCHIP to pick
  reasonable deps. Doesn't want to manually manage 50 transitive
  publisher keys. Wants "if SMARTCHIP trusts AutoEvolve, I trust
  AutoEvolve (for deps of SMARTCHIP packs)".

- **Scenario C (namespace-scoped):** consumer accepts `base.crypto.*`
  packs from any of three well-known foundation publishers but is
  strict for other namespaces.

None of these are expressible in v0.1.1 policy language. Strict mode is
the only option.

### Proposed v0.1.2 amendment

Extend consumer policy with `trust_inheritance` block:

```yaml
trust_inheritance:
  mode: "strict"          # strict | inherit-from-parent | namespace-scoped
  # For inherit-from-parent:
  max_inherit_depth: 2     # inheritance chain depth limit
  # For namespace-scoped:
  namespace_publishers:
    "base.crypto.*":
      - "did:web:autoevolve.io"
      - "did:web:sovereign-crypto.org"
    "govtech.*":
      - "did:web:smartchip.ie"
```

Default remains `strict` (v0.1.1 behavior). Opt-in to inheritance or
namespace rules.

**Why this matters for the marketplace:** without trust inheritance, the
ecosystem can't have a healthy distribution of publishers. Every
consumer would need to pre-trust every publisher of every transitive
dep — an impossible onboarding burden. With inheritance, foundations
(like AutoEvolve Foundation for `base.crypto.*`) can serve as trust
anchors for common primitives without requiring every consumer to
explicitly allowlist them.

## 4. Other findings

### 4.1 Defense-in-depth extends through deps (D4)

D4 tampered with `base.crypto/pages/pattern.md` after publishing. The
recursive verifier applies full §6 steps to the dep, so S3a content_root
check caught it. No special machinery needed — recursion inherits the
properties of the single-pack verifier.

### 4.2 Error messages need to include dependency path

In D5, the rejection message identifies the failing attestation but not
the dependency path that led there. In deep chains this could be
confusing. Amendment for v0.1.2: recursive verifier should produce a
breadcrumb: `qr-offline@1.0.1 → base.crypto@1.0.0 → [S3b untrusted issuer]`.

### 4.3 Cycle detection works but is usually preempted

D6 intentionally introduced a cycle by making base.crypto depend on
qr-offline. The content_root check caught the manifest modification
first, before the cycle detection layer ran. This means cycle detection
is only exercised when:
- Both packs in the cycle are LEGITIMATELY built (signed by real
  publisher keys) with mutual deps
- Neither is tampered

This would be an unusual configuration — usually an authoring error.
Cycle detection remains as defense-in-depth but is not a primary check.

### 4.4 Semver works with minimal implementation

`^1.0` matches `1.0.0`, `1.2.3`, etc. Does NOT match `2.0.0`. The 50-line
implementation in verify_recursive.py is sufficient for dogfood.
Production would use `packaging.version` or equivalent.

## 5. Spec amendments for v0.1.2 (consolidated)

From this dogfood + the v0.1.1 dogfood findings:

1. **Add `trust_inheritance` block to consumer policy** (from D5 — this dogfood)
2. **Recursive verifier produces dependency path breadcrumbs on failure** (from 4.2)
3. **Add §6.4 "Defense-in-depth layers" explaining when each check is load-bearing** (from v0.1.1 dogfood)
4. **Reclassify B5 as integrity sanity check, not security control** (from v0.1.1 dogfood)
5. **Require dogfood test suite include key-compromise scenario** (from v0.1.1 dogfood)
6. **Require dogfood test suite include cross-publisher dependency** (from this dogfood)
7. **Add max_depth policy option** (currently hardcoded to 8)
8. **Standardize registry_hint URL schemes**: `https://`, `file://`, `ipfs://`,
   `did:`  — document which must be supported

## 6. Deliverables

```
dep-chain-test/
├── pack_builder.py                   # shared build utilities
├── build_base_pack.py                # base.crypto.ed25519-signing builder
├── build_qr_pack.py                  # qr-offline@1.0.1 builder with real dep
├── verify_recursive.py               # recursive verifier + 6 tests
└── registry/                         # local filesystem registry
    ├── base.crypto.ed25519-signing/
    │   └── 1.0.0/                    # full signed pack
    └── smartchip.govtech.qr-offline-authorization/
        └── 1.0.1/                    # full signed pack
```

## 7. Cumulative status

| Artifact | Status |
|---|---|
| Spec v0.1 | Superseded |
| Spec v0.1.1 | Authoritative |
| v0.1.2 amendments | 8 clarifications identified, not yet applied |
| Reference implementation | Working: 2 packs, 2 publishers, 14 total tests across 3 test suites |
| Test coverage | Tampering ✓, key compromise ✓, cross-publisher ✓, semver ✓, cycles ✓ |
| Crypto used | Real Ed25519 throughout; no mocks, no placeholders |

We now have enough working infrastructure to sensibly approach either
Q2 (registry API — because we've simulated one and found the pain
points), Q1b (policy evolution — patent-relevant), or the patent claims
draft (enablement is now strong).
