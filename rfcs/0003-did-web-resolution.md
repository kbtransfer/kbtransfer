---
rfc: 0003
title: did:web HTTPS resolution
status: draft
phase: 5
depth: medium
breaks_v1_decision: none
depends_on: [0001]
authors: [kbtransfer-core]
---

# RFC-0003 — `did:web:` HTTPS resolution

## 1. Problem

Spec v0.1.1 §6.3 says:

> `did:web:*` identifiers MAY be resolved online at allowlist-provisioning
> time (fetch `https://{domain}/.well-known/did.json`, extract keys), but
> MUST NOT be resolved per-verification.

That MAY is currently a NEVER. v1 ships zero DID-resolution code. Every
publisher key in v1 lives in the registry's `publishers/<did-safe>/keys.json`
file and is added by the registry operator at admission time. The
publisher's own DID document is **never fetched**.

This is fine when the registry is the trust root for publisher keys. It
breaks down when:

- A publisher rotates a key on their DID document but the registry
  cache is stale; consumers get verification errors with no path to
  recovery short of waiting for the operator to refresh.
- A consumer wants to verify a pack pulled from registry A using the
  *publisher's authoritative* keys, not registry A's claim about them
  (defense-in-depth — registry compromise becomes detectable).
- A publisher exists in multiple registries with divergent key bundles
  (one is stale; one is correct). Consumer has no canonical reference.

RFC-0003 implements the spec's `MAY` — once, at allowlist provisioning
time, with strict offline-verifiability preservation.

## 2. Non-goals

- **No per-verification fetching.** Spec §6.3 explicitly forbids it.
  Verification stays cryptographic-only against locally cached keys.
- **No `did:key:`, `did:ion:`, `did:plc:`, etc.** v0.2 stays
  `did:web:`-only. Other DID methods are RFC-00xx (Phase 6+).
- **No DID document write operations.** Publishers update their
  documents out-of-band on their own infrastructure.
- **No fully W3C-compliant DID resolver.** We implement the minimal
  subset needed for the registry spec §6.2 schema.

## 3. Design

### 3.1 The resolver

```
reference/kb_did/
├── __init__.py
├── resolver.py     # WebDidResolver
└── cache.py        # local-disk cache + integrity wrapper
```

```python
class WebDidResolver:
    def resolve(
        self,
        did: str,                   # "did:web:smartchip.ie"
        *,
        force_refresh: bool = False,
    ) -> ResolvedDid: ...

@dataclass(frozen=True)
class ResolvedDid:
    did: str
    document_url: str
    document_hash: str              # sha256 of fetched bytes
    keys: list[PublisherKey]
    fetched_at: datetime
    cache_age_seconds: int          # 0 if force_refresh or cache miss
```

`did:web:example.com` → `https://example.com/.well-known/did.json`.
Spec-defined per W3C did:web; this RFC carries no novelty here.

### 3.2 Cache

`~/.cache/kbtransfer/did/<did-safe>/document.json` plus
`~/.cache/kbtransfer/did/<did-safe>/document.json.meta`:

```json
{
  "url": "https://smartchip.ie/.well-known/did.json",
  "fetched_at": "2026-04-15T10:00:00Z",
  "document_hash": "sha256:...",
  "ttl_seconds": 86400
}
```

Default TTL: **24 hours**. Configurable in `.kb/policy.yaml`:

```yaml
did_resolution:
  enabled: true
  cache_ttl_seconds: 86400
  refresh_strategy: "lazy"   # lazy | scheduled | never
  on_fetch_failure: "use-stale"  # use-stale | error | strict-no-stale
```

`refresh_strategy: never` collapses RFC-0003 back to v1 behavior — DID
documents are never fetched, consumer relies entirely on registry's
`publishers/<did-safe>/keys.json`. Useful for air-gapped deployments.

### 3.3 Integration with the trust store

`reference/kb_pack/verify.py` exposes `PublisherKeyResolver`. RFC-0003
adds a new implementation:

```python
class DidBackedPublisherKeyResolver(PublisherKeyResolver):
    def __init__(
        self,
        did_resolver: WebDidResolver,
        registry: Registry | None = None,   # fallback
    ): ...

    def keys_for(self, publisher_id: str) -> list[PublisherKey]:
        # 1. Try DID document (cached or fresh per TTL).
        # 2. If DID resolution fails AND registry given AND
        #    on_fetch_failure == "use-stale": fall back to registry cache.
        # 3. If both fail: raise PublisherKeyResolverError.
        ...
```

Consumer policy picks the resolver:

```yaml
trust:
  publisher_key_resolver: "did-backed"   # did-backed | registry-only
  on_did_registry_disagreement: "prefer-did"   # prefer-did | error | warn
```

### 3.4 Disagreement handling

When DID document and registry cache disagree on the key set for a
publisher, this is a **trust-relevant event**. The recursive verifier
(`kb_pack/dependency.py`) MUST surface it:

```
RecursiveVerificationResult(
    ok=False,
    step="key_disagreement",
    message="publisher 'did:web:smartchip.ie' has key 'k1' in DID "
            "document but key 'k1-old' in registry "
            "https://registry.example.com — policy says 'error'",
    breadcrumb=["my-pack@1.0.0 -> base.crypto@1.2.3"],
)
```

Three policy outcomes:

- `prefer-did` (default for individual / team tier): use DID document
  keys; log warning if they differ from registry. Verification proceeds.
- `error` (default for enterprise tier): hard fail on any disagreement.
  Operator must investigate.
- `warn`: use DID document keys; surface a non-blocking warning.

## 4. Spec amendment

Spec v0.1.1 §6.3 stays normatively identical. v0.2 spec amends it with:

- `did:web:` resolver SHOULD honor a TTL-based cache.
- Fetched document MUST be hashed; cache stored alongside hash.
- Disagreement between DID document and registry cache is consumer-
  policy-driven; registry's claim is never authoritative over
  publisher's own DID document.
- `did:web:` resolution MUST use HTTPS (TLS); plain HTTP rejected.

This is an additive amendment — v0.1.1 consumers (which don't resolve
DIDs at all) keep working.

## 5. Security model

| Threat | Mitigation |
|---|---|
| MITM on DID fetch | TLS + system trust store |
| DID document compromise | Out of scope — publisher's domain is the trust root for `did:web:` by definition |
| Registry lies about publisher keys | DID document overrides; disagreement surfaces per policy |
| Stale DID document | TTL refresh; `force_refresh` available; `on_fetch_failure: strict-no-stale` for paranoid consumers |
| Replay of an old DID document version | Mitigated by RFC-0004 timestamping (when both ship) |

**Critical invariant:** verification still happens against a local key
set. Network reachability of the publisher's domain at verification
time is NOT required. The DID resolver runs on a TTL, on
allowlist-provisioning, or on explicit `force_refresh` — never inside
`verify_pack()`. Air-gapped consumers stay air-gapped.

## 6. Interaction with RFC-0001

DID resolution uses HTTPS, which Phase 4 ships first. The `did:web:`
fetcher reuses `kb_registry.transports.https`'s configured `httpx`
client — same retry budget, same proxy settings, same trust store.
Single code path for "kbtransfer fetches over TLS."

## 7. Test plan

- `tests/test_did_resolver.py`
  - Fixture DID document at `tests/fixtures/did/smartchip.ie.json`.
  - Mock httpx; resolve cold → cache → hit; force_refresh bypasses
    cache; TLS error returns stale per policy.
- `tests/test_did_backed_resolver.py`
  - Round-trip with registry cache: matching keys → no disagreement.
  - Mismatched keys → disagreement event; policy `error` raises;
    `prefer-did` proceeds with DID keys.
- `tests/adversarial/test_d9_did_divergence.py`
  - Registry has key K1, DID has K2 superseding K1; pack signed with
    K2 verifies under `prefer-did`, fails under `registry-only`.
  - DID document fetch fails with TLS error; `use-stale` falls back
    to registry; `strict-no-stale` errors.
  - DID document tampered after cache (hash mismatch on next refresh)
    → cache invalidated, refetched.

## 8. Breaking-change analysis

| Change | Breaks v1? |
|---|---|
| New `kb_did` package | No — additive |
| `PublisherKeyResolver` gains a second impl | No — protocol unchanged |
| Default `publisher_key_resolver` per tier | **One change** — enterprise tier defaults to `did-backed` with `on_disagreement: error`. Individual / team default to `registry-only` to preserve v1 behavior with explicit opt-in for v2 semantics. |

Document the enterprise-tier default change in the v0.2 migration
notes; it is the only behavioral break.

## 9. Open questions

1. **DID document signature.** Spec §6.2 doesn't require the document
   itself to be signed. Should we add a signed DID document option
   (sign the JSON with a long-lived publisher root key, rotate
   shorter-lived signing keys inside)? Not in this RFC; track for
   Phase 6.
2. **Multi-domain publishers.** `did:web:smartchip.ie` and
   `did:web:smartchip.com` could be the same legal entity. v0.2 treats
   them as fully separate; deduplication is consumer-policy only.
3. **`.well-known` path collisions.** Some publishers may already host
   a `did.json` for other purposes. Spec is explicit: the path is
   reserved per W3C did:web. Out of scope.

## 10. Effort estimate

~700 lines: `kb_did/resolver.py` (~200), `kb_did/cache.py` (~120),
`PublisherKeyResolver` integration (~80), policy plumbing (~80),
tests (~220). One dogfood report jointly with RFC-0004 as `reports/08`.
