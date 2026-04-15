# KBTRANSFER — v2 Protocol Roadmap

**Status:** Planning. v1 complete 2026-04-14 at commit `4e63478`.
**Predecessor:** `ROADMAP.md` (v1 — Phase 1-3, all done).
**Charter:** lift the protocol from "local + git registry" to "networked,
independently verifiable, federated" without breaking v1 consumer code.

---

## What v1 left on the table

`reports/06 §7` enumerates v1's honest limits. v2 closes the ones that
production deployments hit first:

| ID | Limit (from `reports/06 §7`)                       | RFC      | Phase |
|----|----------------------------------------------------|----------|-------|
| L1 | No `https://` / `git+https://` registry transports | RFC-0001 | 4     |
| L2 | No `registry/submit/0.1` MCP tool over the wire    | RFC-0002 | 4     |
| L3 | No automatic `did:web:` resolution                 | RFC-0003 | 5     |
| L4 | No RFC 3161 timestamping (spec amendment A4)       | RFC-0004 | 5     |
| L5 | No registry-federation trust protocols             | RFC-0005 | 6     |
| L6 | No formal revocation protocol (spec §7)            | RFC-0006 | 6     |

Two further v0.2 candidates from the registry spec §8 are deliberately
parked in **Deferred / Exploratory** below — not enough field signal yet
to commit to a design.

---

## Phasing

Three phases, each closing with a dogfood report (`reports/07-09`) the
same way v1 did. Each phase is independently shippable; later phases
build on earlier ones but do not invalidate them.

### Phase 4 — Network (transport layer)

**Charter:** lift the registry from "local filesystem only" to "fetchable
over the public internet, submittable without a git PR." After Phase 4 a
publisher SHOULD be able to call `kb/publish/0.1` and have the pack land
in a remote registry without the operator merging anything by hand.

| RFC      | Topic                                 | Depth  | Status  |
|----------|---------------------------------------|--------|---------|
| RFC-0001 | `https://` / `git+https://` transport | medium | shipped |
| RFC-0002 | `registry/submit/0.1` MCP tool        | medium | shipped |

**Phase gate:** `examples/sample-registry-http/` FastAPI app runs
end-to-end against a hosted instance — submit → verify → fetch —
without touching git. Proven locally via
`tests/test_sample_registry_http.py` in the 2026-04-15 dogfood
(`reports/07-rfc0002-registry-submit.md`).

### Phase 5 — Identity & time

**Charter:** make publisher identity and signing-time independently
verifiable. Today both depend on the registry's caching (publisher keys
shipped in `publishers/<did-safe>/keys.json`; timestamps publisher-claimed).
Phase 5 lets a consumer re-derive both from authoritative sources.

| RFC      | Topic                                | Depth  |
|----------|--------------------------------------|--------|
| RFC-0003 | `did:web:` HTTPS resolution          | medium |
| RFC-0004 | RFC 3161 timestamp tokens            | medium |

**Phase gate:** D-suite extension (D7-D9) covering DID-document
divergence, expired timestamps, and TSA failover.

### Phase 6 — Federation & revocation

**Charter:** make trust composable across registries and recoverable
after compromise. v1 has zero protocol for either: each registry is an
island, and a leaked key can only be retired by the publisher updating
their DID document and hoping the registry refreshes.

| RFC      | Topic                                | Depth  |
|----------|--------------------------------------|--------|
| RFC-0005 | Registry federation trust protocol   | medium |
| RFC-0006 | Revocation protocol                  | medium |

**Phase gate:** new test suite `tests/federation/` proves a consortium
registry that mirrors a foundation registry rejects pulls of revoked
keys within `freshness_window` while preserving offline verifiability.

---

## Deferred / Exploratory

Items the v1 reports flagged but for which there is no production
signal yet to drive a design. Listed so future contributors do not
re-derive the motivation; **no RFC** until field feedback exists.

### D-1 — Pub/sub for new pack versions

**Motivation.** Consumers today poll `registry/list_versions/0.1` or
re-run `kb/registry_search/0.1`. A subscribed consumer cannot react to
"upstream pack X published 1.2.0" except on its own polling cadence.

**Why no RFC:** registry spec §8 explicitly defers pub/sub to v0.2 and
the v1 dogfood never surfaced a polling-pain incident — the polling
loop in `examples/sample-registry/.github/workflows/verify-pack.yml`
runs on PR merge and that has been sufficient.

**Blocked by:** at least one operator deploying a registry with a
subscriber base large enough that polling is expensive (>~100 daily
active consumers per pack). Promote to RFC-0007 then.

### D-2 — Payment rails

**Motivation.** The pack manifest carries `license_class:
commercial-with-warranty`, but enforcement is publisher-side and
out-of-band. A consortium that wants metered access has no protocol
hook.

**Why no RFC:** locked design decision #7 deferred the revenue model;
without it any payment protocol is design-by-committee. The four trust
roles (open / consortium / private + permissionless flag) cover the
known operator types without payment metadata.

**Blocked by:** a v1 design-decision revisit on revenue model. Until
then payment metadata is documentation-only, not protocol.

---

## What v2 deliberately does NOT change

The ten locked design decisions from v1 (see `memory/design_decisions_v1.md`)
remain authoritative. v2 RFCs MUST NOT contradict any of them. In
particular:

- **Storage stays plain markdown + git** (decision #3). Phase 4 adds
  network *transport* for the registry, not for the wiki.
- **Pack granularity stays "pattern, ~5 pages"** (decision #6). v2
  does not introduce mini-packs or collections.
- **Subscriptions stay isolated read-only** (decision #10). Federation
  in Phase 6 is between registries, not between users' wikis.

Any RFC proposing a change to a locked decision MUST flag it explicitly
in its frontmatter `breaks_v1_decision:` field. None of RFC-0001 through
RFC-0006 do.

---

## Versioning convention

- Spec text version stays at `v0.1.x` until Phase 6 ships. v0.2 is the
  joint publication after all six RFCs are implemented and dogfooded.
- MCP tool versions bump per-tool via additive minor (`0.1 → 0.1.1`)
  when an RFC adds optional fields to existing tools. New tools land
  at `0.1`.
- Attestation envelope bumps to `autoevolve-attestation/<kind>/0.2.0`
  when timestamping (RFC-0004) lands; consumers ignore unknown fields
  per v0.1.1 forward-compat rules.

---

## Reading order

If reading top-to-bottom for the first time:

1. This file (you are here).
2. `rfcs/0001-https-transport.md` — concrete transport changes.
3. `rfcs/0002-registry-submit.md` — operator-side write path.
4. `rfcs/0003-did-web-resolution.md` — independent identity.
5. `rfcs/0004-rfc3161-timestamping.md` — independent time.
6. `rfcs/0005-federation-trust.md` — composing trust across registries.
7. `rfcs/0006-revocation.md` — withdrawing trust.

Each RFC stands alone but assumes familiarity with the v1 spec
(`specs/current/`) and the v1 dogfood reports (`reports/04-06`).

---

*End of v2 roadmap. Phase 4 begins when the first RFC moves to
`status: accepted`.*
