---
rfc: 0005
title: Registry federation trust protocol
status: draft
phase: 6
depth: medium
breaks_v1_decision: none
depends_on: [0001, 0002, 0003]
authors: [kbtransfer-core]
---

# RFC-0005 — Registry federation trust protocol

## 1. Problem

v1 federation is **consumer-driven** (registry spec §7): the consumer
maintains a list of registries to query, ranks them by preference, and
verifies every pack independently. Registries don't know about each
other.

This is the right default — it keeps registries dumb and consumers in
control. But it doesn't solve four real cases:

1. **Mirror chains.** Registry M mirrors content from registry F. A
   consumer pulling from M wants to know "is this mirror current?
   does M actually have the same view of pack X as F?" Today: no
   protocol hook, consumer just trusts M.
2. **Consortium endorsement.** A consortium registry C wants to say
   "we trust packs originally published in foundation registry F." A
   consumer querying C should be able to follow the trust chain to F
   without re-pinning F as a top-level registry.
3. **Failover discovery.** Consumer's preferred registry A goes
   offline. A's last `describe()` could have advertised "if I'm down,
   try B and C" — registry-published failover hints. Today: hardcoded
   in consumer policy or out-of-band.
4. **Cross-registry pack identity.** Same `pack_id@version` published
   in registries A and B — are they the same pack (mirror) or
   different packs that happen to collide? Today: `content_root`
   comparison is consumer's job and never required.

RFC-0005 introduces a **declarative federation graph** registries can
publish, plus consumer-side traversal rules. Critically, it does NOT
change the v0.1.1 invariant that "registry lies cause DoS, not
compromise" — every fetched pack is still verified end-to-end.

## 2. Non-goals

- **No registry-to-registry RPC.** Registries do not call each other.
  The federation graph is published statically; consumers traverse it.
- **No global trust root.** No "registry of registries." Federation is
  a per-registry assertion; consumers compose their own view.
- **No automatic mirror sync.** Mirror semantics are operational;
  this RFC describes how to *declare* a mirror, not how to keep one
  in sync.
- **No cross-registry write operations.** Submit (RFC-0002) targets a
  single registry. Replication is out-of-band.

## 3. Design

### 3.1 The federation document

Each registry publishes one new file:

`{registry_root}/federation.json`

Served at HTTP path `GET /v0.1/federation` (registry spec §4 extended).

```json
{
  "spec": "autoevolve-registry-federation/0.1",
  "registry_id": "did:web:registry.example.com",
  "registry_role": "consortium",
  "updated_at": "2026-04-15T11:00:00Z",
  "mirrors": [
    {
      "of": "did:web:registry.foundation.org",
      "of_url": "https://registry.foundation.org",
      "scope": "all",                          // all | namespace | pack
      "namespace_glob": null,                  // when scope=namespace
      "pack_glob": null,                       // when scope=pack
      "policy": "transparent",                 // transparent | curated
      "last_synced_at": "2026-04-15T10:00:00Z"
    }
  ],
  "endorses": [
    {
      "registry_id": "did:web:registry.foundation.org",
      "registry_url": "https://registry.foundation.org",
      "endorsement_scope": "publisher_keys",   // publisher_keys | submission_review | both
      "expires_at": "2027-04-15T00:00:00Z",
      "rationale_url": "https://example.com/why-we-endorse-foundation"
    }
  ],
  "failover": [
    "https://registry-mirror-a.example.com",
    "https://registry-mirror-b.example.com"
  ],
  "signature": {
    "algorithm": "ed25519",
    "key_id": "registry-2026Q2",
    "value": "..."
  }
}
```

The signature covers the canonical JSON of the document **excluding**
the signature field itself. The signing key MUST appear in the
registry's own DID document at `did:web:{registry_host}` (RFC-0003
flow, applied to the registry-as-publisher).

### 3.2 Mirror semantics

A mirror declaration `{of: F, scope: all, policy: transparent}` means:

- M serves packs that came originally from F.
- For any pack present in M and F at the same `pack_id@version`,
  `content_root` MUST match (consumer-checkable).
- M's `last_synced_at` is advisory — consumer-visible staleness signal.

`policy: curated` means M intentionally serves a *subset* of F (e.g.,
removed packs that violated M's content moderation). Same
content-root invariant for what is present, but M MAY omit packs.

A mirror does NOT inherit F's publisher signatures or trust store —
publisher keys are pulled from the publisher's DID document
independently (RFC-0003).

### 3.3 Endorsement semantics

`endorses` is the trust-chain primitive. When registry C endorses
registry F:

- `endorsement_scope: publisher_keys` — C asserts "publishers admitted
  by F should be considered admitted by C." A consumer querying C
  for a pack published originally on F can follow the endorsement to
  fetch F's `publisher_keys/0.1` if C's local cache is missing the
  publisher.
- `endorsement_scope: submission_review` — C asserts "F's submit-time
  validation (RFC-0002 §4) is at least as strict as ours." Used by
  consortia that import packs from foundation registries without
  re-validating from scratch.
- `endorsement_scope: both` — both above.

**Crucially:** endorsement is advisory. Consumer policy decides
whether to honor it:

```yaml
federation:
  honor_endorsements: false           # false | true | per-registry
  endorsement_per_registry:
    "did:web:registry.example.com":
      honor: true
      max_chain_depth: 1              # don't follow C → F → G
      scopes_allowed: ["publisher_keys"]
```

Default off — preserves v1 behavior. Opt-in for consumers who want
the federation graph to drive trust decisions.

### 3.4 Failover semantics

Consumer's resolver, on connection failure to registry A, MAY consult
A's last cached `federation.json` to find failover candidates. Tries
them in declared order. A failover registry MUST have its own
`describe()` that lists itself — i.e., we don't blindly trust A's
recommendation; we verify the failover target is a real registry that
identifies itself.

### 3.5 Trust-graph traversal limits

Without limits, federation chains could explode (A endorses B,
endorses C, endorses A — cycle). Consumer policy:

```yaml
federation:
  max_chain_depth: 3
  cycle_detection: true               # always on; this is just a doc flag
  graph_cache_ttl_seconds: 86400
```

### 3.6 Disagreement handling

When two endorsers in the consumer's federation view assert
contradictory things about a publisher (e.g., one says key K is
admitted, another says K is rejected), the consumer's policy decides:

```yaml
federation:
  on_endorsement_conflict: "most-restrictive"   # most-restrictive | most-permissive | error
```

Default: `most-restrictive` — when in doubt, don't trust.

## 4. MCP tool surface

### 4.1 `kb/registry_federation/0.1` (new, read-only)

```python
async def kb_registry_federation(registry_url: str) -> dict:
    registry = open_registry(registry_url)
    return await registry.federation()    # parses + verifies signature
```

Returns the parsed federation.json with an additional `signature_valid`
boolean from local verification.

### 4.2 `kb/registry_resolve/0.1` extended

Adds optional `follow_endorsements: bool` (default `false`). When
`true`, if the registry doesn't have the pack, the resolver consults
the federation graph and tries endorsers (subject to
`max_chain_depth`).

This is the only existing-tool change in this RFC. Backward
compatible — default preserves v1 behavior.

## 5. Spec amendment

`autoevolve-registry-spec-v0.2.md`:

- New §11 "Federation graph protocol" specifying `federation.json`
  schema, semantics of `mirrors`, `endorses`, `failover`.
- §3 (MCP tool surface) gains `registry/federation/0.1`.
- §7 "Federation + multi-registry" updated: v1 was consumer-side-only;
  v2 adds optional registry-published graph that consumers MAY honor.
- §8 non-goals removes "no registry mirroring protocol" if it was
  there (it isn't; new ground).

## 6. Security model

| Threat | Mitigation |
|---|---|
| Forged federation.json | Signature required; key in registry's DID document |
| Endorsement loop / cycle | Consumer-side `max_chain_depth` + cycle detection |
| Malicious endorsement (M endorses attacker's registry) | Endorsements are advisory; consumer policy `honor_endorsements: false` is default; per-registry override |
| Mirror serves wrong content | `content_root` must match across mirrors; consumer verifies every pack |
| Failover redirects to attacker-controlled registry | Attacker-controlled registry's packs still must verify against publisher's DID document keys (RFC-0003); DoS, not compromise |
| Endorsement scope expansion (scope=publisher_keys interpreted as scope=both) | Strict scope matching; unknown / superset scopes treated as no-endorsement |

The federation protocol's worst-case behavior is **the same as v1's**:
a malicious or compromised registry can DoS, mislead about discovery,
or hide content. It cannot inject content that passes pack
verification. RFC-0005 expands the discovery/UX surface without
expanding the cryptographic trust surface.

## 7. Test plan

- `tests/test_federation_doc.py`
  - Build, sign, verify a federation.json against a fixture DID.
  - Tampered field → signature fails.
  - Missing required field (`registry_id`, etc.) → schema error.
- `tests/test_federation_traversal.py`
  - C endorses F; consumer asks C for pack only on F; with
    `follow_endorsements: true` resolver fetches from F.
  - Cycle: A endorses B endorses A; depth limit kicks in.
  - Conflict: two endorsers disagree; `most-restrictive` policy
    rejects.
- `tests/federation/test_mirror_consistency.py`
  - Mirror M and origin F both claim pack X@1.0.0; same content_root
    → fine. Different content_root → consumer-visible mirror error.

## 8. Breaking-change analysis

| Change | Breaks v1? |
|---|---|
| New `federation.json` file (optional) | No — additive |
| New MCP tool | No — additive |
| `registry_resolve/0.1` `follow_endorsements` arg | No — opt-in, default false |
| Default `honor_endorsements: false` | No — preserves v1 |

No tier-default change in this RFC. Enterprise tier may want
`honor_endorsements: true, on_conflict: most-restrictive` as a policy
template, but that's documentation-level, not protocol.

## 9. Interaction with RFCs 0003 and 0006

- **RFC-0003 (DID resolution)** is required: the federation document
  signature key is on the registry's DID document. Without RFC-0003,
  the only way to bootstrap a registry's signing key is the same
  out-of-band cache pattern v1 uses for publisher keys — works, but
  doesn't scale to a federation of dozens.
- **RFC-0006 (revocation)** interacts via endorsement scope. A
  publisher's revocation MUST be honored regardless of endorsement —
  endorsement of a registry never overrides the publisher's own
  revocation list.

## 10. Open questions

1. **Endorsement chains across DID methods.** v0.2 is `did:web:`-only
   (RFC-0003). When more DID methods come, can a `did:web:` registry
   endorse a `did:plc:` registry? Yes in principle; defer trust-graph
   normalization to that RFC.
2. **Federation gossip.** Should consumers periodically pull
   `federation.json` from every known registry to keep their local
   graph fresh, or only on resolve-failure? Lean toward
   resolve-failure-driven — periodic pull is bandwidth waste for
   small consumers.
3. **Endorsement revocation.** When does an endorser take back an
   endorsement? `expires_at` handles time-bounded; for early
   revocation, just publish a new federation.json with the
   endorsement removed and bump `updated_at`. Consumers refresh per
   `graph_cache_ttl_seconds`.

## 11. Effort estimate

~700 lines: federation document module (~250), MCP tool (~100),
resolver `follow_endorsements` path (~150), tests (~200). Joint
dogfood with RFC-0006 as `reports/09-phase6-federation-revocation-dogfood.md`.
