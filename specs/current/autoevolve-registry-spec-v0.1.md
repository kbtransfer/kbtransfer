# AutoEvolve Registry Specification v0.1

**Status:** Draft for discussion
**Depends on:** `autoevolve-spec-v0.1.1.md` (pack format + verification)
**Scope:** Registry API, MCP tool surface, multi-registry federation.
**Out of scope:** Payment rails, DRM, content delivery optimization.

---

## 1. Design principles

1. **Registry is untrusted.** A registry is a convenience layer —
   discovery, resolution, distribution. It is NOT a trust root. Nothing
   a registry says is taken at face value by consumers; every claim is
   either locally verifiable (via pack signatures) or advisory (e.g.,
   search ranking).

2. **Registry lies cause DoS, not compromise.** A malicious or buggy
   registry can hide packs, serve stale metadata, or redirect to wrong
   URLs. All of these are detected (hash mismatch, signature failure)
   or tolerable (user retries on another registry). None compromise
   cryptographic guarantees.

3. **MCP-first API.** The primary interface is a set of MCP tools
   agents call. HTTP is a parallel interface for non-agent clients.
   Tool shapes are stable; transport is fungible.

4. **Federation is native, not bolted on.** Multiple registries are
   expected. Consumer policy declares which registries to query and in
   what preference order. No global registry hierarchy, no root of trust.

5. **Permissionless publishing.** Anyone can submit a pack to a public
   registry. Registry performs minimal sanity checks (valid manifest,
   signature verifies, attestations present). It does NOT vet
   publishers, content, or quality. Trust decisions are pushed entirely
   to consumer policy.

---

## 2. Three registry roles

A registry operator chooses its role at deployment time. These are
policy choices, not protocol choices — the API is identical across all.

### 2.1 Open registry
Permissionless submission. Anyone with a valid DID and a well-formed
pack can publish. Analog: npm, crates.io. Spam and low-quality content
are expected; consumers rely on ranking + their own policy for
filtering.

### 2.2 Consortium registry
Invitation-only publisher set. Registry operator maintains an admission
list. Publisher admission process is out-of-band. Analog: Maven
Central with namespace coordination, or Docker Hub official images.
Lower noise; consumer policies can trust consortium membership as a
signal.

### 2.3 Private registry
Internal to an organization. Only organization members publish and
consume. Analog: private npm, Artifactory. Often the first registry a
consumer queries before falling back to public ones.

**Protocol implication:** zero. The same MCP tool set and HTTP API
work for all three. Role differences show up in the `describe()`
response and in which publishers' keys the registry lists.

---

## 3. MCP tool surface

The authoritative interface for agents. Tool names prefixed with
`registry/` for namespacing; version suffix on each tool for stability.

### 3.1 `registry/describe/0.1`

**Purpose:** return registry self-description. Consumer calls this on
first contact with a new registry.

**Input:** none.

**Output:**
```json
{
  "spec": "autoevolve-registry/0.1",
  "name": "AutoEvolve Public Registry",
  "endpoint": "https://registry.autoevolve.io",
  "role": "open",                      // open | consortium | private
  "submission_policy": "permissionless-with-signature",
  "publisher_count": 1247,
  "pack_count": 8931,
  "version_count": 42107,
  "last_updated": "2026-04-14T08:00:00Z",
  "contact": "ops@autoevolve.io",
  "terms_url": "https://registry.autoevolve.io/terms",
  "supported_tools": [
    "registry/describe/0.1",
    "registry/search/0.1",
    "registry/resolve/0.1",
    "registry/list_versions/0.1",
    "registry/get_manifest/0.1",
    "registry/get_attestations_index/0.1",
    "registry/list_publishers/0.1",
    "registry/publisher_keys/0.1",
    "registry/submit/0.1"             // omitted if registry is read-only
  ]
}
```

### 3.2 `registry/search/0.1`

**Purpose:** find packs matching natural-language or structured query.

**Input:**
```json
{
  "query": "offline authorization QR border",   // optional, natural language
  "filters": {                                   // all optional
    "namespace_prefix": "govtech.",
    "license_class": ["open", "commercial-with-warranty"],
    "redaction_level_min": "standard",
    "publisher_id": "did:web:smartchip.ie",
    "jurisdiction": "EU"
  },
  "ranking": "relevance",                        // relevance | recency | downloads | rating
  "limit": 20,
  "cursor": null                                 // pagination cursor from previous response
}
```

**Output:**
```json
{
  "results": [
    {
      "pack_id": "smartchip.govtech.qr-offline-authorization",
      "latest_version": "1.0.1",
      "publisher_id": "did:web:smartchip.ie",
      "publisher_display_name": "SMARTCHIP Limited",
      "title": "QR Offline Authorization — Basic Pattern",
      "summary": "Short-lived signed QR tokens verified offline...",
      "namespace": "govtech.access-control",
      "license_class": "commercial-with-warranty",
      "redaction_level": "strict",
      "evaluation_score": 0.91,
      "total_versions": 3,
      "last_published": "2026-04-14T09:00:00Z",
      "relevance": 0.87
    }
  ],
  "cursor": "eyJvZmZzZXQiOjIwfQ==",
  "total_matches": 47
}
```

**Consumer note:** `relevance`, `evaluation_score`, and similar ranking
signals are registry-advisory. Consumer policy may disregard them.

### 3.3 `registry/resolve/0.1`

**Purpose:** given a pack_id and version constraint, return the best
matching version's fetch metadata. This is the primary tool for
dependency resolution.

**Input:**
```json
{
  "pack_id": "base.crypto.ed25519-signing",
  "constraint": "^1.0",                // semver constraint
  "prefer": "highest"                   // highest | stable | exact-pinned
}
```

**Output:**
```json
{
  "resolved": {
    "pack_id": "base.crypto.ed25519-signing",
    "version": "1.2.3",
    "publisher_id": "did:web:autoevolve.io",
    "publisher_key_ids": ["autoevolve-foundation-2026Q1"],
    "canonical_url": "https://registry.autoevolve.io/packs/base.crypto.ed25519-signing/1.2.3.tar",
    "content_root": "sha256:abc...",
    "pack_root": "sha256:def...",
    "size_bytes": 47829,
    "published_at": "2026-03-15T12:00:00Z",
    "mirrors": [
      "https://mirror.europe.autoevolve.io/packs/.../1.2.3.tar",
      "https://smartchip.ie/mirrored/base.crypto.ed25519-signing-1.2.3.tar"
    ]
  }
}
```

**Integrity note:** `content_root` and `pack_root` are advisory hints.
Consumer MUST recompute from fetched content and verify publisher
signature. If registry lied about roots, consumer's verification fails
— DoS, not compromise.

### 3.4 `registry/list_versions/0.1`

**Purpose:** enumerate available versions of a pack.

**Input:**
```json
{ "pack_id": "smartchip.govtech.qr-offline-authorization" }
```

**Output:**
```json
{
  "pack_id": "smartchip.govtech.qr-offline-authorization",
  "versions": [
    { "version": "1.0.0", "published_at": "2026-04-10T14:00:00Z", "yanked": false },
    { "version": "1.0.1", "published_at": "2026-04-14T09:00:00Z", "yanked": false }
  ]
}
```

**Yanked versions:** a publisher MAY mark a version as "yanked" (do not
use). Registries SHOULD surface this. Consumer policy MAY accept yanked
versions but SHOULD warn. Yanking is advisory, not revocation.

### 3.5 `registry/get_manifest/0.1`

**Purpose:** fetch the manifest only, without the full pack. Useful
for agents evaluating relevance before committing to download.

**Input:**
```json
{
  "pack_id": "smartchip.govtech.qr-offline-authorization",
  "version": "1.0.1"
}
```

**Output:** the raw `pack.manifest.yaml` content as string plus its
hash so consumer can verify on full download.

### 3.6 `registry/get_attestations_index/0.1`

**Purpose:** fetch attestation summaries without downloading full pack.
Returns the key fields from each attestation as a flat index.

**Input:** same as `get_manifest`.

**Output:**
```json
{
  "pack_id": "...",
  "version": "1.0.1",
  "attestations": {
    "redaction": {
      "level": "strict",
      "policy_id": "smartchip-redaction-policy-v2",
      "reviewer_count": 2,
      "adversarial_targets_passed": 4,
      "residual_risk_count": 2
    },
    "evaluation": {
      "composite_score": 0.91,
      "test_case_pass_rate": 1.0
    },
    "provenance": {
      "source_documents": 23,
      "autoevolve_sessions": 87
    },
    "license": {
      "spdx": "LicenseRef-smartchip-commercial-v1",
      "class": "commercial-with-warranty"
    }
  }
}
```

Registry computes this index at submission time. Consumer MUST NOT
trust these values for security decisions; they are purely for
discovery UX.

### 3.7 `registry/list_publishers/0.1`

**Purpose:** enumerate publishers known to this registry.

**Input:**
```json
{ "filter": { "namespace_prefix": "govtech." }, "limit": 100, "cursor": null }
```

**Output:**
```json
{
  "publishers": [
    {
      "id": "did:web:smartchip.ie",
      "display_name": "SMARTCHIP Limited",
      "namespaces_published": ["govtech.access-control", "gaming.ticketing"],
      "pack_count": 12,
      "first_seen": "2026-03-01T00:00:00Z",
      "admission_status": "permissionless"   // permissionless | admitted | suspended
    }
  ],
  "cursor": null
}
```

### 3.8 `registry/publisher_keys/0.1`

**Purpose:** fetch public keys for a publisher. Used during consumer's
trust store bootstrap.

**Input:**
```json
{ "publisher_id": "did:web:smartchip.ie" }
```

**Output:**
```json
{
  "publisher_id": "did:web:smartchip.ie",
  "keys": [
    {
      "key_id": "smartchip-2026Q2",
      "algorithm": "ed25519",
      "public_key_hex": "5e7508...",
      "valid_from": "2026-04-01T00:00:00Z",
      "valid_until": "2026-09-30T23:59:59Z",
      "revoked": false
    },
    {
      "key_id": "smartchip-2026Q1",
      "algorithm": "ed25519",
      "public_key_hex": "3a9d10...",
      "valid_from": "2026-01-01T00:00:00Z",
      "valid_until": "2026-04-01T00:00:00Z",
      "revoked": false,
      "superseded_by": "smartchip-2026Q2"
    }
  ],
  "did_document_url": "https://smartchip.ie/.well-known/did.json",
  "did_document_hash": "sha256:..."
}
```

**Consumer note:** registry is caching what the publisher's DID
document says. Consumer MAY fetch `did_document_url` directly to
verify. Mismatch between registry cache and authoritative DID document
is a reason to distrust THAT REGISTRY, not the publisher.

### 3.9 `registry/submit/0.1`

**Purpose:** publish a new pack to the registry. Write operation.

**Input:**
```json
{
  "pack_tarball_base64": "...",       // or pack_url to be fetched by registry
  "pack_url": null,
  "notes": "Initial release of 1.0.1 with base.crypto dependency."
}
```

**Output:**
```json
{
  "accepted": true,
  "pack_id": "smartchip.govtech.qr-offline-authorization",
  "version": "1.0.1",
  "registry_url": "https://registry.autoevolve.io/packs/.../1.0.1.tar",
  "published_at": "2026-04-14T09:15:00Z"
}
```

**Registry validation at submit time:**
- Manifest parses
- pack.lock parses
- content_root and pack_root recompute correctly
- Publisher signature over pack_root verifies against publisher's current keys
- All four required attestations present and internally signed
- Attestations' `content_root` matches pack's `content_root`
- residual_risk_notes non-empty (v0.1.1 requirement)
- Version doesn't already exist (no overwrite)

Registry REJECTS submission if any check fails. Registry does NOT
evaluate content quality, license terms, or consumer suitability.

---

## 4. HTTP API (parallel interface)

Every MCP tool has a REST equivalent:

| MCP tool | HTTP method + path |
|---|---|
| `registry/describe/0.1` | `GET /v0.1/describe` |
| `registry/search/0.1` | `POST /v0.1/search` |
| `registry/resolve/0.1` | `GET /v0.1/resolve/{pack_id}?constraint=^1.0` |
| `registry/list_versions/0.1` | `GET /v0.1/packs/{pack_id}/versions` |
| `registry/get_manifest/0.1` | `GET /v0.1/packs/{pack_id}/{version}/manifest` |
| `registry/get_attestations_index/0.1` | `GET /v0.1/packs/{pack_id}/{version}/attestations-index` |
| `registry/list_publishers/0.1` | `GET /v0.1/publishers` |
| `registry/publisher_keys/0.1` | `GET /v0.1/publishers/{publisher_id}/keys` |
| `registry/submit/0.1` | `POST /v0.1/submit` (multipart upload) |

Content-Type: `application/json` for structured responses; `application/x-tar`
for pack tarball downloads at canonical_url.

**No auth required for read operations** on open/consortium registries.
Private registries use bearer tokens (RFC 6750). Submit operations
authenticated with publisher signature at manifest level, not at HTTP
level — the signature IS the authentication.

---

## 5. Pack resolution protocol (consumer-side)

End-to-end flow when an agent needs pack X:

```
1. Agent parses user's intent or reads manifest dependency entry.
2. Consumer policy determines which registries to query:
     registries = policy.registries[namespace_prefix]
                  or policy.registries.default
3. For each registry in preference order:
     a. registry.resolve(pack_id, constraint) → candidate
     b. If no candidate, try next registry
     c. If candidate found:
        - Fetch candidate.canonical_url (or mirror on retry)
        - Apply v0.1.1 §6 verification
        - If verification fails → log, try next candidate
        - If verification succeeds → done
4. If all registries exhausted → VerificationError("no source")
```

**Multi-registry failover** is a consumer concern, not a protocol
concern. Registries do NOT know about each other.

**Dependency resolution** recurses this entire flow for each dep.
Different deps may resolve from different registries.

---

## 6. Publisher registration

How a publisher becomes known to a registry:

### 6.1 First-publish flow (permissionless open registry)

1. Publisher generates Ed25519 keypair.
2. Publisher publishes DID document at `https://{domain}/.well-known/did.json`
   listing their public key(s) with `key_id`s.
3. Publisher builds a pack, signs with private key.
4. Publisher calls `registry/submit/0.1` with the pack.
5. Registry:
   - Extracts publisher.id from manifest
   - Fetches DID document from publisher's domain (once, cached)
   - Verifies pack's signatures against keys in DID document
   - If valid: admits publisher to its directory, stores pack
6. Consumer later discovers pack via `registry/search/0.1`.

### 6.2 DID document schema (minimal)

```json
{
  "@context": "https://www.w3.org/ns/did/v1",
  "id": "did:web:smartchip.ie",
  "verificationMethod": [
    {
      "id": "did:web:smartchip.ie#smartchip-2026Q2",
      "type": "Ed25519VerificationKey2020",
      "controller": "did:web:smartchip.ie",
      "publicKeyMultibase": "z6Mk..."
    }
  ]
}
```

Full W3C DID document schema supported; only `verificationMethod` is
required.

### 6.3 Key rotation

Publisher updates DID document with new `verificationMethod` entry. Old
entry remains with optional `superseded_by` annotation. Registry
refreshes its cache on a schedule or on signature verification failure.

Publisher can publish with old key even after rotation, as long as old
key is in DID document and not `revoked`. This allows smooth overlap
periods.

### 6.4 Revocation (out-of-band)

Publisher removes compromised key from DID document and adds revocation
entry. Registry refreshes, marks key as revoked in subsequent
`publisher_keys/0.1` responses. Already-published packs signed with
revoked key remain in registry; consumer policy decides how to treat
them.

---

## 7. Federation + multi-registry

### 7.1 Consumer policy

```yaml
registries:
  default:
    - { url: "https://registry.autoevolve.io", role: "open" }
  namespaces:
    "smartchip.*":
      - { url: "https://registry.smartchip.ie", role: "private" }
      - { url: "https://registry.autoevolve.io", role: "open" }
    "base.crypto.*":
      - { url: "https://registry.cryptofoundation.org", role: "consortium" }
      - { url: "https://registry.autoevolve.io", role: "open" }

fallback_to_default: true     # if namespace match fails, try default list
query_in_parallel: false      # sequential preserves preference order
cache_ttl_seconds: 3600       # cache resolve() results
```

### 7.2 Cross-registry dependencies

A pack published in registry A may depend on a pack published in
registry B. The dep's `registry_hint` field (v0.1.1 amendment C3)
advises consumer where to look first. Consumer policy MAY override.

### 7.3 Registry mirroring

Any registry MAY cache or mirror content from any other. Mirrors
expose the same API; hashes must still verify. A mirror is just
another registry for consumer purposes.

### 7.4 No global namespace authority

Pack IDs are not globally unique by protocol. `smartchip.foo` in
registry A may be different from `smartchip.foo` in registry B. Consumers
distinguish by including registry identity in their local index. In
practice, namespace convention (reverse-DNS under publisher's domain)
provides strong pseudo-uniqueness without a central authority.

---

## 8. Deliberate non-goals

- **Quality scoring.** Registry does not rank packs by quality beyond
  surfacing publisher-provided evaluation scores. Reputation systems are
  out of scope.
- **Paid access / entitlements.** If a pack is commercial, payment and
  license enforcement are publisher concerns, not registry. The pack
  itself is freely downloadable; running it without a valid license is
  the consumer's legal exposure.
- **Content moderation.** Registry operators may have their own
  moderation policies (spam, malware, regulated content) but these are
  operator choices, not protocol requirements.
- **Persistent search index.** Registries may forget old entries. Long-
  term archival is out of scope (use IPFS, Zenodo, or publisher's own
  storage).
- **Real-time notifications.** Pub/sub for new pack versions deferred
  to v0.2. Consumer polls `list_versions` for now.

---

## 9. Minimal viable registry

For dogfooding: a registry prototype needs to implement only 4 of the 9
MCP tools to be useful:

1. `describe/0.1`
2. `search/0.1`
3. `resolve/0.1`
4. `get_manifest/0.1`

The remaining 5 can be stubbed or deferred. `submit/0.1` is required
for a working publish flow but can be initially implemented as "drop
files in a directory" (exactly what we did in the dep-chain dogfood).

Implementation size estimate:
- Storage: filesystem tree `packs/{pack_id}/{version}/` — zero code
- Search: full-text over manifest fields with SQLite FTS5 — ~100 lines
- Resolve: semver matching — ~30 lines (we already have this)
- HTTP server: FastAPI or equivalent — ~150 lines
- MCP adapter: map each HTTP endpoint to MCP tool — ~100 lines

Total: ~400 lines of Python for a working minimal registry. A weekend
project at most.

---

## 10. Next-step candidates

- **Q2a — Build minimal registry as dogfood.** ~400 lines, validates
  this spec the same way build.py/verify.py validated v0.1.1.
- **Q2b — Consumer policy DSL for registry preferences.** The YAML in
  §7.1 is illustrative; make it formal.
- **Q2c — Registry federation trust model.** Can a consortium registry
  declare that it trusts specific open registries? Mirror relationships,
  etc. This is the non-trivial federation case.
- **Return to Q1b** — Policy evolution loop (patent-relevant).
- **Return to Q3** — Consumer policy engine DSL.
- **Patent claims draft** — enough reference implementation exists now
  to write concrete USPTO claims.

---

*End of registry spec v0.1 draft.*
