---
rfc: 0002
title: registry/submit/0.1 — permissionless wire-level publish
status: shipped
phase: 4
depth: medium
breaks_v1_decision: none
depends_on: [0001]
authors: [kbtransfer-core]
shipped_at: 2026-04-15
---

# RFC-0002 — `registry/submit/0.1` MCP tool

## 1. Problem

v1 publishes a pack by:

1. `kb/publish/0.1` writes `published/{pack_id}-{version}.tar` locally.
2. The publisher manually opens a PR against the registry repo,
   uploading the tarball + a publishers/keys.json update if first time.
3. CI runs `examples/sample-registry/scripts/verify_submission.py`
   (.github/workflows/verify-pack.yml).
4. Operator merges; index regenerates.

This works for low-volume curated registries (the v1 dogfood scenario)
and is exactly the model decision #4 chose. It does NOT work when:

- Publishers run unattended (e.g., a CI job in their own repo that
  emits a new pack version on each release).
- The registry is "open" (registry spec §2.1) and expects high
  submission volume — manual PR review is the bottleneck.
- A consortium registry wants programmatic admission of pre-vetted
  publishers without per-pack human gating.

`registry/submit/0.1` is sketched in the registry spec §3.9 already.
RFC-0002 turns the sketch into a wire-level tool that piggybacks on
RFC-0001's HTTPS transport.

## 2. Non-goals

- **No replacement of git-PR mode.** The sample registry's PR workflow
  remains the recommended on-ramp for curated registries. Submit-tool
  is for *additional* submission pathways, not the only one.
- **No payment / entitlement signaling.** Publisher pays operator
  out-of-band if relevant.
- **No per-publisher rate limits in this RFC.** Operators implement
  rate limits at HTTP layer; protocol carries no quota fields.

## 3. Tool surface

### 3.1 Input

```json
{
  "registry_url": "https://registry.example.com",
  "pack_tarball_path": "/path/to/published/foo-1.0.0.tar",
  "notes": "Initial release with base.crypto dependency."
}
```

`pack_tarball_path` is local; the MCP server reads the file and posts
it to the registry. Alternative `pack_url` (registry pulls it) is
spec-allowed but deferred — first deployments will be push-mode.

### 3.2 Output (success)

```json
{
  "accepted": true,
  "pack_id": "smartchip.govtech.qr-offline-authorization",
  "version": "1.0.1",
  "registry_canonical_url": "https://registry.example.com/v0.1/packs/smartchip.govtech.qr-offline-authorization/1.0.1.tar",
  "published_at": "2026-04-15T09:15:00Z",
  "registry_attestation": {
    "spec": "autoevolve-registry-attestation/0.1",
    "registry_id": "did:web:registry.example.com",
    "received_at": "2026-04-15T09:14:58Z",
    "checks_passed": [
      "manifest_parse",
      "lock_parse",
      "content_root_recompute",
      "signature_verify",
      "attestations_present",
      "residual_risk_notes_nonempty",
      "version_uniqueness"
    ],
    "signature": {"algorithm": "ed25519", "key_id": "registry-2026Q2", "value": "..."}
  }
}
```

The optional `registry_attestation` is **new in v0.2** (registry
spec §3.9 didn't include it). It records the registry's claim to have
performed the submit-time checks listed in registry spec §3.9. This is
NOT a security attestation — consumers re-verify everything — but it
gives the publisher a signed receipt useful for compliance and
debugging.

### 3.3 Output (rejection)

```json
{
  "accepted": false,
  "errors": [
    {
      "check": "signature_verify",
      "message": "publisher key 'smartchip-2026Q1' not in DID document at https://smartchip.ie/.well-known/did.json",
      "remediation": "publish DID document with new key, or sign with a current key"
    }
  ]
}
```

Errors are structured. Each `check` field corresponds 1:1 to a string
in the success response's `checks_passed`. Publishers can match
remediation hints to specific failures.

## 4. Server-side validation

Registry MUST run all checks the v1 sample registry's
`verify_submission.py` script runs, plus the v0.1.1 §6 verification
flow in full. Concretely, this means consuming the pack the way a
consumer would:

1. Untar to scratch dir; reject if tarball escapes prefix
   (path-traversal).
2. Parse `pack.manifest.yaml`; reject on schema violation.
3. Recompute `content_root` (Merkle); reject on mismatch.
4. Recompute `pack_root`; reject on mismatch.
5. Resolve publisher's current keys from registry's local cache (or
   from DID document per RFC-0003 once Phase 5 lands).
6. Verify pack signature; reject on failure.
7. Verify all four required attestations (provenance, redaction,
   evaluation, license) per spec §5.
8. Reject if `redaction.residual_risk_notes` is empty (v0.1.1
   amendment C1).
9. Reject if `pack_id@version` already exists. **No overwrite, ever.**
   To replace, publisher bumps version per semver.

Rejected pack is NOT stored. Registry MUST NOT keep a copy of any
content that failed verification (legal exposure, especially for the
"could be PII" failure modes).

## 5. Authentication

The publisher's pack signature **is** the authentication. There is no
HTTP-level credential for submit on open registries.

For consortium and private registries:

- **Consortium:** registry maintains a publisher allowlist (§2.2);
  submit is rejected with `not_admitted` for unknown publishers. This
  RFC adds a new check to §4: `publisher_admitted` — runs *before*
  signature verification when the registry's role is `consortium`.
- **Private:** in addition to the allowlist, an HTTP bearer token MUST
  accompany the request (RFC 6750). Token issuance is out-of-band.

Token authentication does NOT replace the signature check; both
required.

## 6. MCP tool integration

A new MCP tool `kb/registry_submit/0.1` exposes this in the reference
server:

```python
# reference/kb_mcp_server/tools/registry_submit.py
async def kb_registry_submit(
    registry_url: str,
    pack_tarball_path: str,
    notes: str = "",
) -> dict:
    registry = open_registry(registry_url)
    if not isinstance(registry, HttpsRegistry):
        raise ValueError("submit requires HTTPS registry transport")
    return await registry.submit(Path(pack_tarball_path), notes=notes)
```

`kb/publish/0.1` gets an optional `submit_to_registry: str | null`
field. If set, after writing the local tarball it calls
`kb_registry_submit` with the produced path. Backward compatible —
default `null` keeps v1 behavior.

## 7. Sample-registry template update

`examples/sample-registry/` gains an HTTP shim — a tiny FastAPI app
under `examples/sample-registry-http/` that:

- Wraps the existing filesystem layout.
- Exposes the registry spec §4 HTTP API.
- Implements `POST /v0.1/submit` that runs the validation in §4
  above, then either commits the new tarball + index update to the
  underlying git repo (operator-set "commit on submit" mode) or stages
  it for human review (default mode — preserves the existing PR-based
  curation).

This lets v1's curated workflow keep working while exposing a wire
endpoint for unattended submitters. Operators choose per-deployment.

## 8. Test plan

- `tests/test_registry_submit.py`
  - Round-trip: publish locally → submit → resolve → fetch → verify.
  - Reject: tampered tarball after publish (signature breaks).
  - Reject: duplicate version.
  - Reject: missing attestation.
  - Consortium reject: unknown publisher.
- `tests/adversarial/test_d8_submit_abuse.py`
  - Path-traversal tarball entry → rejected before extract.
  - 100MB tarball (oversize) → rejected at upload limit.
  - Replay of a previously-submitted tarball → rejected as duplicate
    (NOT stored a second time).

## 9. Breaking-change analysis

| Change                                              | Breaks v1? |
|-----------------------------------------------------|------------|
| New MCP tool `kb/registry_submit/0.1`               | No — additive |
| `kb/publish/0.1` optional `submit_to_registry` arg  | No — opt-in |
| Sample registry HTTP shim (new directory)           | No — additive |
| Registry attestation in submit response             | No — consumers ignore unknown fields |

Existing publishers using the manual git-PR path keep working
unchanged. The HTTP shim is opt-in per registry deployment.

## 10. Open questions

1. **Async submit.** For very large packs (still rare in v1's pattern
   granularity), should submit return `202 Accepted` with a polling
   URL? Defer until first oversize-pack incident.
2. **Submit attestation key rotation.** The registry's signing key
   for `registry_attestation` must be discoverable. Use the same DID
   pattern as publishers: `https://{registry_host}/.well-known/did.json`.
   This is implicit in the registry spec but not yet enforced; this
   RFC makes it normative.
3. **Yank operation.** Spec §3.4 mentions yanking. Not in this RFC —
   becomes RFC-0002a if needed before Phase 6.

## 11. Effort estimate

~500 lines: `tools/registry_submit.py` (~80), `kb_registry/transports/https.py`
submit method (~120), sample-registry HTTP shim (~200), tests (~200).
One dogfood report, jointly with RFC-0001 as `reports/07`.
