---
rfc: 0004
title: RFC 3161 timestamp tokens on attestations
status: draft
phase: 5
depth: medium
breaks_v1_decision: none
depends_on: [0001]
authors: [kbtransfer-core]
---

# RFC-0004 — RFC 3161 timestamp tokens on attestations

## 1. Problem

Spec v0.1.1 §4 amendment **A4** (and the §7 non-goal): every
attestation's `issued_at` is publisher-claimed. The signature covers
that timestamp, so a publisher cannot forge it later — but a publisher
*can* sign an attestation today and backdate `issued_at` to last year.
Nothing in v1 binds the signature event to actual wall-clock time.

This is fine when consumers don't care about time. It breaks when:

- Revocation enters the picture (RFC-0006). "Was this signed before or
  after the publisher's key was revoked?" can't be answered without an
  external time anchor.
- Compliance auditors require provable signing time
  (sarbox-style chain of custody, GDPR breach disclosure windows,
  financial audit deadlines).
- A publisher's key is later compromised; "every signature with key K
  after time T is suspect" requires a way to date signatures
  independent of the publisher.

RFC 3161 (Time-Stamp Protocol) is the well-known IETF answer.

## 2. Non-goals

- **No mandatory timestamping in v0.2.** Optional per consumer policy
  and per pack publisher policy. Default: off, preserving v1 behavior.
  Becomes default-on in v0.3 if Phase 5 dogfood shows TSA reliability
  is good.
- **No custom TSA protocol.** RFC 3161 only.
- **No "trusted clock" registry-side.** Registry's `received_at`
  remains advisory (registry spec §3.9 receipt). Independent TSA is
  the trust anchor.
- **No long-term archival timestamping (LTA).** That is RFC 4998
  (ERS) territory, out of scope until Phase 6+.

## 3. Design

### 3.1 Attestation envelope amendment

Adds a `timestamp` field (optional, may appear on any attestation):

```json
{
  "spec": "autoevolve-attestation/redaction/0.2.0",
  "pack": "smartchip.govtech.qr-offline-authorization@1.0.1",
  "content_root": "sha256:...",
  "issuer": "did:web:smartchip.ie",
  "issued_at": "2026-04-15T10:00:00Z",
  "redaction_level": "strict",
  "policy_applied": "smartchip-redaction-policy-v2",
  "policy_version": "2.1",
  "categories_redacted": ["pii.email", "pii.phone", "client.name"],
  "residual_risk_notes": ["..."],
  "signature": {"algorithm": "ed25519", "key_id": "smartchip-2026Q2", "value": "..."},
  "timestamp": {
    "spec": "rfc3161",
    "tsa_url": "https://timestamp.identrust.com",
    "tsa_cert_chain_sha256": "sha256:...",
    "token_base64": "MII...",
    "covered_digest": "sha256:...",
    "stamped_at": "2026-04-15T10:00:13Z"
  }
}
```

`covered_digest` is the SHA-256 of the canonical JSON of the
attestation **excluding** the `timestamp` field (chicken-and-egg —
timestamping operates on the bytes-to-be-stamped, not on the
post-stamped bytes). Concretely: build the attestation, sign it,
hash the canonical JSON of the signed-but-not-timestamped form,
request a token, attach the token in `timestamp.token_base64`.

`tsa_cert_chain_sha256` lets consumers verify they trust the same TSA
chain the publisher used. Expanded chain may be cached at
`~/.cache/kbtransfer/tsa/<sha256>.pem` for offline verification.

### 3.2 Publisher flow

1. Publisher's `kb/publish/0.1` (extended) constructs each attestation
   as today.
2. If `policy.timestamping.enabled: true`:
   a. Canonicalize attestation (without `timestamp` field).
   b. Compute SHA-256 → `covered_digest`.
   c. Build RFC 3161 TimestampReq; POST to TSA URL.
   d. Receive TimestampToken; verify TSA's signature; extract
      `genTime`.
   e. Attach `timestamp` block to attestation.
3. Pack with timestamped attestations; rest of v1 publish flow
   unchanged.

If TSA call fails (network / 5xx / cert issue), behavior depends on
policy:

- `on_tsa_failure: skip` — emit attestation without timestamp; warn.
- `on_tsa_failure: error` — abort publish.
- `on_tsa_failure: queue` — write pack to `published-pending/`, retry
  TSA later. Not in this RFC; defer to operator tooling.

### 3.3 Consumer flow

Verification gains a step in `verify_pack()` (new section in spec
§6, after step 5 "verify attestations"):

> **5.5. Verify timestamp tokens.** For each attestation that carries
> a `timestamp` field, recompute `covered_digest` from canonical JSON
> of the attestation excluding the timestamp; verify the RFC 3161
> token covers that digest; verify the TSA signature against the
> consumer's TSA trust anchors; record `stamped_at`. Disagreement
> between `issued_at` (publisher claim) and `stamped_at` (TSA) wider
> than `consumer.timestamp.max_clock_skew_seconds` (default 600) is a
> verification failure.

Consumer policy:

```yaml
timestamping:
  required: false                     # if true, untimestamped attestation = fail
  trusted_tsa_certs: "system"          # system | path/to/anchors.pem | empty
  max_clock_skew_seconds: 600
  on_tsa_unreachable_at_verify: "ignore"   # ignore | warn | error
```

`on_tsa_unreachable_at_verify` is for the case where the consumer
wants to re-validate the TSA's certificate chain online. Default is
`ignore` because token verification only needs the TSA's public key,
which is in the cached cert chain. Online check is a defense-in-depth
opt-in.

### 3.4 TSA selection

Free / public TSAs at the time of writing:

- `https://timestamp.digicert.com`
- `https://timestamp.identrust.com`
- `https://freetsa.org/tsr`
- `https://rfc3161.ai.moda` (community, less battle-tested)

Reference implementation defaults to a list of two (DigiCert + IdenTrust)
with retry-on-other. Operators may override:

```yaml
timestamping:
  tsa_urls:
    - "https://timestamp.digicert.com"
    - "https://timestamp.identrust.com"
  tsa_round_robin: false   # false = try in order, true = randomize
```

### 3.5 Library choice

`asn1crypto` + `cryptography` (already a transitive dep) cover RFC
3161 token construction and parsing. `rfc3161-client` (small PyPI
package) wraps the wire protocol — adopt or vendor a minimal subset.

## 4. Spec amendment

`autoevolve-spec-v0.2.0.md` (joint v2 spec publication after Phase 6):

- §4 attestation envelope: add optional `timestamp` field (schema in
  §3.1 of this RFC).
- §6 verification flow: insert step 5.5 (per §3.3 above).
- §7 amendment A4: mark resolved by RFC-0004; remove from non-goals.

v0.1.1 consumers ignore unknown fields and do not perform step 5.5;
they keep working against v0.2 packs (just without timestamp
verification — same security posture they have today).

## 5. Security model

| Threat | Mitigation |
|---|---|
| Backdated `issued_at` | TSA's `genTime` cross-checks; > `max_clock_skew` = fail |
| Forged TSA token | TSA cert chain verified against consumer's anchors |
| TSA compromise | Multi-TSA policy (two independent TSAs reduce single-point trust) — captured in operator guidance, not yet protocol-enforced |
| TSA goes offline forever | Token already signed — verification works from cached cert chain. Future timestamps need new TSA. |
| Replay an old token onto a new attestation | `covered_digest` binding — token only validates against the original digest |

## 6. Interaction with RFC-0006 (revocation)

The combined story is the v2 trust model's centerpiece:

> "This attestation was signed by key K at time T per TSA. Key K was
> revoked at time R per the publisher's revocation list. If T < R,
> trust the signature; if T > R, reject."

Without RFC-0004 the "if T < R" check is meaningless because T is
publisher-claimed. With it, revocation is enforceable retroactively
without invalidating legitimately-pre-revocation packs. This is the
critical piece that makes RFC-0006 useful.

## 7. Test plan

- `tests/test_timestamping.py`
  - Build attestation, request token from a mock TSA fixture, verify
    digest binding.
  - Tampered attestation post-stamp → covered_digest mismatch → fail.
  - Clock skew > 600s → fail.
  - Unknown TSA cert chain → fail.
- `tests/adversarial/test_d10_timestamp_attacks.py`
  - Token from one attestation re-attached to another: digest fails.
  - Backdated `issued_at` (signed today, claims last year): TSA
    `genTime` is today; `max_clock_skew` exceeded → fail.
  - Forged TSA token (self-signed): cert chain not in trust store →
    fail.

## 8. Breaking-change analysis

| Change | Breaks v1? |
|---|---|
| New optional `timestamp` field in attestations | No — additive |
| New verification step | No — only runs when field present |
| Spec attestation envelope version `0.2.0` | No — consumers ignore unknown spec versions per forward-compat |
| Default `policy.timestamping.required: false` | No — opt-in |

If a consumer sets `timestamping.required: true` against a v0.1.1 pack
(no timestamps), verification fails with a clear "no timestamp token"
error. This is the intended escalation path.

## 9. Open questions

1. **TSA bundling.** Should the reference implementation bundle a
   set of TSA root certs (like browsers bundle CAs) or rely entirely
   on the system trust store? Lean toward system-only; bundling a
   list creates an update treadmill.
2. **`covered_digest` over signature vs over signed body.** The RFC
   above stamps the post-signature attestation. Alternative: stamp
   the body before signing, attach token alongside signature. The
   chosen design is closer to standard PKCS#7 SignedData practice;
   keep.
3. **Multi-TSA stamps.** Publisher could attach multiple
   `timestamp[]` entries from different TSAs for defense-in-depth.
   Spec change is trivial (array vs single), but consumer verification
   must handle "any one valid" vs "all valid." Defer to v2.1.

## 10. Effort estimate

~600 lines: timestamping module (~250 incl. ASN.1 plumbing),
verification step (~80), tests (~270). Joint dogfood with RFC-0003 as
`reports/08-phase5-identity-time-dogfood.md`.
