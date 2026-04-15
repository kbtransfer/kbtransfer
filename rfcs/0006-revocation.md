---
rfc: 0006
title: Revocation protocol
status: draft
phase: 6
depth: medium
breaks_v1_decision: none
depends_on: [0001, 0003, 0004]
authors: [kbtransfer-core]
---

# RFC-0006 — Revocation protocol

## 1. Problem

Spec v0.1.1 §7 explicit non-goal:

> **Revocation protocol.** Bad packs are rejected via consumer policy
> (e.g., blacklist rule). Formal revocation lists deferred to v0.2.

Today the only way to "revoke" a pack is:

- Publisher updates DID document to mark a key revoked
  (`revoked: true`). Future packs signed by that key are rejected by
  consumers who fetch the DID document. This is RFC-0003's territory.
- Consumer adds the pack to a local blacklist. Doesn't propagate to
  other consumers.

Both fail at the case that motivates this RFC: **a previously trusted
pack turns out to be bad** — supply-chain attack, license violation
discovered later, factual error with downstream impact, leaked PII
that bypassed the redaction pipeline. The publisher needs to declare
"do not use pack X@1.0.0" and have that declaration propagate to
consumers without each consumer maintaining a private blacklist.

This is the well-known PKI revocation problem applied to packs.

## 2. Non-goals

- **No registry-level revocation list.** The publisher controls
  revocation; the registry distributes it. Registry deciding to
  unilaterally revoke a publisher's pack is a moderation action
  (registry spec §8 non-goal: content moderation), not protocol.
- **No "revoke and re-issue same version."** Versions are immutable;
  revocation marks a version as do-not-use, not as replaceable.
- **No grace period for already-deployed packs.** Consumers using a
  revoked pack get an immediate verification error on next refresh.
  Operational rollout is consumer-side concern.
- **No CRL distribution point negotiation.** Single canonical URL per
  publisher; no CRL profile selection.

## 3. Design

### 3.1 The publisher revocation list

Publisher publishes one new file at:

`https://{publisher_domain}/.well-known/kbtransfer-revocations.json`

```json
{
  "spec": "autoevolve-revocation/0.1",
  "publisher_id": "did:web:smartchip.ie",
  "updated_at": "2026-04-15T12:00:00Z",
  "next_update_at": "2026-04-22T12:00:00Z",
  "revocations": [
    {
      "pack_ref": "smartchip.govtech.qr-offline-authorization@1.0.0",
      "content_root": "sha256:...",
      "revoked_at": "2026-04-15T11:30:00Z",
      "reason": "leaked-pii",
      "reason_code": "redaction-failure",
      "remediation": "upgrade to 1.0.1 which removes the affected page",
      "supersedes_with": "smartchip.govtech.qr-offline-authorization@1.0.1"
    }
  ],
  "key_revocations": [
    {
      "key_id": "smartchip-2026Q1",
      "revoked_at": "2026-04-15T11:25:00Z",
      "reason": "key-compromise",
      "reason_code": "private-key-disclosed"
    }
  ],
  "signature": {
    "algorithm": "ed25519",
    "key_id": "smartchip-2026Q2",
    "value": "..."
  }
}
```

The file has TWO sections:

- `revocations[]` — pack-level. Specific `pack_ref` is do-not-use.
  `content_root` MUST match the pack's actual content_root (so a
  registry that lies about which pack is at which version can't
  trick consumers into rejecting the wrong content).
- `key_revocations[]` — key-level. Every pack signed by the listed
  key is suspect. Combined with RFC-0004 timestamps to date
  signatures.

`reason` is free text for humans; `reason_code` is from a small
controlled vocabulary so consumer policy can route reactions:

| `reason_code` | Meaning |
|---|---|
| `redaction-failure` | Pack content includes PII that should have been redacted |
| `factual-error` | Pack content is wrong in a way that materially misleads consumers |
| `license-issue` | Pack license terms changed or were misstated |
| `private-key-disclosed` | Signing key is known compromised (key revocations only) |
| `superseded-critical` | Newer version fixes a security issue; old version unsafe to keep using |
| `other` | Anything else; check `reason` text |

`next_update_at` is a freshness commitment. If a consumer fetches and
sees `next_update_at` in the past, the list is stale — policy decides
whether to trust it.

The signature is over canonical JSON (excluding the signature field).
Signing key MUST be a current, non-revoked key in the publisher's DID
document — you can't use a revoked key to sign a revocation list.

### 3.2 Consumer flow

Verification step added (spec §6 step 5.6, after timestamping):

> **5.6. Check revocation status.** For each pack being verified
> (root + transitively each dependency):
>
> 1. Resolve publisher's revocation list URL from DID document
>    (default: `/.well-known/kbtransfer-revocations.json`).
> 2. Fetch (cached per `revocation.cache_ttl_seconds`).
> 3. Verify list signature against current publisher keys.
> 4. If list is stale (now > `next_update_at` + grace) and policy
>    requires fresh: fail.
> 5. If pack's `pack_ref` appears in `revocations[]` and `content_root`
>    matches: fail with reason.
> 6. If pack's signing key appears in `key_revocations[]`:
>    - If pack carries an RFC-0004 timestamp earlier than the
>      `revoked_at`: pass (signed before revocation).
>    - Otherwise: fail.

### 3.3 Cache and offline behavior

`~/.cache/kbtransfer/revocations/<did-safe>/list.json` plus
`.meta` with `fetched_at` and `next_update_at`.

Policy:

```yaml
revocation:
  enabled: true
  cache_ttl_seconds: 3600
  on_fetch_failure: "use-stale"        # use-stale | error | strict-no-stale
  staleness_grace_seconds: 86400        # tolerate this much past next_update_at
  required_for_verify: true
  on_unknown_publisher: "skip"          # skip | error
```

`on_unknown_publisher: skip` (default) means a publisher with no
revocation file is treated as "no revocations" — safer default during
v2 rollout when most publishers haven't published a list yet.
Enterprise tier may flip to `error` to require all publishers to
publish revocation files.

### 3.4 Key revocation + timestamp interaction

This is the single most important piece. Without RFC-0004, a key
revocation is **all or nothing** — every pack signed by the revoked
key becomes suspect, even ones legitimately signed years before the
compromise. With RFC-0004:

```
For pack P signed by key K:
    if K not revoked:
        verify normally
    elif K revoked at time R:
        if P has timestamp t and t < R - clock_skew:
            verify normally   # signed legitimately before revocation
        else:
            fail with key_revoked
```

Without timestamps, consumers fall back to "treat key revocation as
applying to all packs" — strict, but makes long-running publishers
disastrous to recover after a compromise. Operators SHOULD enable
timestamping (RFC-0004) before publishing key revocations, or accept
the operational pain.

### 3.5 Revocation propagation

There is no push protocol. Distribution is pull-based with TTL — same
model as DID resolution (RFC-0003). For low-latency revocation
(security-critical), the publisher MAY:

- Lower TTL on responses to `/.well-known/kbtransfer-revocations.json`.
- Send out-of-band notifications (email, security advisory) directing
  consumers to refresh.

These are operational, not protocol. The protocol guarantees: any
consumer that pulls within their `cache_ttl_seconds + grace` will see
the revocation.

## 4. MCP tool surface

### 4.1 `kb/check_revocations/0.1` (new)

```python
async def kb_check_revocations(
    pack_path: str,           # extracted pack on disk
    *,
    force_refresh: bool = False,
) -> dict:
    """
    Returns:
      {
        "ok": bool,
        "revocations_checked": [...],
        "violations": [...],
        "stale_lists": [...],
      }
    """
```

Lets agents proactively check their currently-installed subscriptions
without re-running full `verify_pack`. Useful for periodic
"is anything I depend on revoked?" sweeps.

### 4.2 `kb/verify/0.1` extended

Adds optional `check_revocations: bool` (default `true`). False
preserves v1 behavior for tests / offline scenarios.

## 5. Spec amendment

`autoevolve-spec-v0.2.0.md`:

- §4 (attestation envelope): no change. Revocation lives outside the
  pack.
- §6 (verification): new step 5.6 (per §3.2 of this RFC).
- §7 non-goals: remove "no revocation protocol"; mark resolved by
  RFC-0006.
- New §10 "Revocation list format" — full schema from §3.1.

`autoevolve-registry-spec-v0.2.md`:

- New §12 "Revocation visibility" — registry SHOULD surface a
  publisher's revocation status in `publisher_keys/0.1` responses
  and in `registry/search/0.1` results (advisory). Registry MUST
  NOT modify or filter publisher revocation lists.

## 6. Security model

| Threat | Mitigation |
|---|---|
| Forged revocation list | Signature required, key from publisher's DID document |
| Attacker-suppressed revocation (DoS to keep bad packs trusted) | `next_update_at` freshness; `staleness_grace_seconds` cap; `required_for_verify` policy |
| Backdated `revoked_at` to invalidate legitimate timestamps | Key for signing list cannot itself be a revoked-then-resurrected key; revocation events are append-only by convention |
| Publisher revokes pack to censor critical content | Out of scope — publisher controls their own packs by definition; consumer policy can pin to specific versions to resist |
| Stale cache used after key compromise | Lower TTL by policy; `force_refresh` available |
| Replay an old revocation list | Signature includes `updated_at`; consumer rejects lists with `updated_at` older than cached |

## 7. Interaction with other RFCs

- **RFC-0001 (HTTPS):** revocation list fetched over HTTPS; same
  transport stack.
- **RFC-0003 (DID):** revocation list URL discovered via DID
  document (publisher MAY publish a `service` entry pointing to a
  non-default location); signing key resolved via DID.
- **RFC-0004 (timestamping):** as explained in §3.4 above, the
  combined story is the v2 trust model's centerpiece. Timestamps
  without revocation are auditable but not actionable. Revocation
  without timestamps is blunt. Together they enable
  point-in-time-correct trust.
- **RFC-0005 (federation):** registries MAY surface revocation status
  in their search/describe responses (advisory). Endorsements never
  override revocations; publisher's revocation list is authoritative.

## 8. Test plan

- `tests/test_revocation_list.py`
  - Build, sign, verify a revocation list against a fixture DID.
  - Tampered field → signature fails.
  - Stale list (next_update_at past + grace exceeded) →
    fresh-required policy fails.
- `tests/test_revocation_check.py`
  - Pack revoked → verify_pack fails with reason_code.
  - Pack signing key revoked, pack timestamp before revocation →
    verify_pack passes.
  - Pack signing key revoked, no timestamp → verify_pack fails with
    key_revoked.
- `tests/adversarial/test_d11_revocation_attacks.py`
  - Suppressed revocation list (offline) + `required_for_verify:
    true` → fail.
  - Forged revocation list signed by attacker-controlled key (not in
    publisher DID document) → signature fails.
  - Replay of an older revocation list (with fewer entries) →
    `updated_at` regression detected; reject.
  - Key revoked with `revoked_at = T`, pack with claimed `issued_at <
    T` but no TSA timestamp → fail (claimed time not trusted).

## 9. Breaking-change analysis

| Change | Breaks v1? |
|---|---|
| New revocation list file (publisher-side) | No — opt-in per publisher |
| New verification step | No — only runs if `check_revocations: true` |
| New MCP tool | No — additive |
| Default `check_revocations: true` | **One change** — v1 packs without revocation files are treated per `on_unknown_publisher: skip`, which is "no revocations" — same effective behavior as v1. Documented but not breaking. |
| Default `revocation.required_for_verify: true` | No — paired with `on_unknown_publisher: skip` to preserve v1 behavior in absence of any publisher publishing a list |

## 10. Open questions

1. **Sub-pack revocation.** Can a publisher revoke a single page
   within a pack rather than the whole pack? Spec decision #6 (~5
   pages, pattern granularity) makes this low-value. Not in v0.2;
   revoke and supersede instead.
2. **Revocation of revocations.** Can a publisher un-revoke (declare
   "false alarm, that pack is fine after all")? Yes — remove the
   entry from the list and bump `updated_at`. Consumers refresh and
   see no revocation. Append-only is a convention, not a hard
   protocol rule.
3. **Cross-publisher revocation propagation.** When a publisher
   depends on another publisher's pack and the upstream is revoked,
   does the downstream publisher have to publish a revocation too?
   Spec strict view: no — recursive verification (v1
   `dependency.py`) catches this at consumer side. Operationally:
   publishers SHOULD publish their own revocation when they know an
   upstream they depend on has been revoked.

## 11. Effort estimate

~750 lines: revocation list module (~250 incl. signing/verifying),
verification step integration (~120), `kb/check_revocations/0.1` MCP
tool (~80), tests (~300). Joint dogfood with RFC-0005 as
`reports/09-phase6-federation-revocation-dogfood.md`.
