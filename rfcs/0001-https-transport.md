---
rfc: 0001
title: HTTPS and git+https registry transports
status: shipped
phase: 4
depth: medium
breaks_v1_decision: none
depends_on: []
authors: [kbtransfer-core]
---

# RFC-0001 — HTTPS and git+https registry transports

> **Status:** shipped as `HttpsRegistry` in
> `reference/kb_registry/registry.py`. See
> `tests/test_registry.py` for sha256-mismatch, path-traversal,
> size-cap, and end-to-end subscribe-over-HTTPS coverage. The
> sections below preserve the original design rationale.

## 1. Problem

`reference/kb_registry/registry.py` currently accepts `file://` and bare
filesystem paths only. `_resolve_registry_root` raises
`RegistryError("unsupported registry URL scheme")` for anything else.
Every v1 dogfood ran against a local checkout of the
`examples/sample-registry/` template; nothing has been pulled across the
network. Production deployments need:

- **HTTPS** for hosted registries that want a regular web origin
  (`https://registry.example.com`).
- **`git+https://`** for the registry-as-git-repo pattern v1 chose
  (decision #4) — letting consumers fetch directly from the GitHub repo
  template without an intermediate web service.

The v1 `Registry` class was written with this expansion in mind: the
docstring says *"the abstraction is intentionally thin so adding a new
URL scheme later is a single new subclass"*. RFC-0001 cashes that
cheque.

## 2. Non-goals

- Generic HTTP (no `http://` — TLS only).
- Other VCS schemes (`git+ssh`, `hg+https`).
- Registry write operations — those are RFC-0002.
- Mirror selection / fastest-mirror logic — registry spec §3.3 lists
  `mirrors[]` already; consumer-side ranking is a follow-up.

## 3. Design

### 3.1 Subclass layout

```
reference/kb_registry/
├── registry.py           # base class + file:// (existing)
├── transports/
│   ├── __init__.py
│   ├── https.py          # HttpsRegistry
│   └── git_https.py      # GitHttpsRegistry
└── ...
```

`open_registry(url)` becomes a dispatcher: parse `urlparse(url).scheme`,
return the matching subclass. The base class stays read-only and
`file://`-only; new schemes are pure additions.

### 3.2 `HttpsRegistry`

Implements the registry spec v0.1 §4 HTTP API (already specified —
this RFC is implementation, not new spec).

| Operation | HTTP call |
|---|---|
| `describe()` | `GET {base}/v0.1/describe` |
| `list_versions(pack_id)` | `GET {base}/v0.1/packs/{pack_id}/versions` |
| `resolve(pack_id, constraint)` | `GET {base}/v0.1/resolve/{pack_id}?constraint={c}` |
| `fetch(pack_id, version, dest)` | follow `canonical_url` → `GET` tarball |
| `publisher_keys(publisher_id)` | `GET {base}/v0.1/publishers/{id}/keys` |
| `search(query, limit)` | `POST {base}/v0.1/search` |

**Auth.** Read operations on open / consortium registries: none. Private
registries: bearer token from env (`KBTRANSFER_REGISTRY_TOKEN_<host>`)
or from `.kb/registry-credentials.yaml` (gitignored). Spec §4 already
mandates RFC 6750.

**Caching.** `fetch()` caches tarballs under
`~/.cache/kbtransfer/registries/<host>/<pack_id>/<version>.tar`,
keyed by the `sha256` from `resolve()` so cache poisoning a registry
that lies about hashes still fails verification at consumer side.

**Retry policy.** Three retries with exponential backoff (1s, 4s, 16s)
on 5xx and connection errors. 4xx: no retry (treat as authoritative).
Total budget: 30s wall-clock per `resolve()` or `fetch()`.

### 3.3 `GitHttpsRegistry`

For `git+https://github.com/org/repo[@ref]` URLs.

**Strategy: shallow clone + cached pull.**

1. First call: `git clone --depth 1 --filter=blob:none {url} <cache>`.
2. Subsequent calls within `cache_ttl_seconds` (default 3600): use cache.
3. After TTL: `git -C <cache> pull --depth 1 --ff-only`.
4. `_resolve_registry_root` returns the cache dir; everything else
   reuses the existing `file://` codepath unchanged.

**Why not full clone:** registry repos can grow to hundreds of MB of
tarballs over time. `--filter=blob:none` lets git fetch tree objects
only on demand (tarballs are blobs).

**Ref selection:** `git+https://...@v0.1.2` pins to a tag; without a
ref, default branch HEAD. Operators MAY publish signed git tags for
audit anchoring; consumers MAY require them via policy
(`registry.require_signed_ref: true`).

### 3.4 Open question — `git+https` cache key

If two consumer machines on the same network both clone the same
registry repo, do they share the cache? Phase 4 v1 says **no** —
per-user cache (`~/.cache/kbtransfer/`). A future content-addressed
network cache (RFC-00xx, Phase 6+) could share at the tarball level
since each tarball already has a registry-vouched sha256.

## 4. Tool surface changes

### 4.1 No new MCP tools

All six existing `kb/registry_*` tools and the recursive verifier in
`kb_pack/dependency.py` already take a `Registry` object — they do not
care which subclass. Wiring is internal to `open_registry()`.

### 4.2 Updated MCP tool input

`kb/registry_describe/0.1`, `kb/registry_search/0.1`,
`kb/registry_resolve/0.1`, and `kb/subscribe/0.1` (registry-mode) all
accept a `registry_url` argument today. Their schemas do not change;
they just start accepting `https://` and `git+https://` schemes that
previously raised.

This is an **additive** change — no version bump on any tool.

## 5. Security model

| Scheme | TLS | Server identity | Content integrity |
|---|---|---|---|
| `file://` | n/a | local FS perms | sha256 from index.json + signature |
| `https://` | required (no `--insecure`) | system trust store | sha256 from index.json + signature |
| `git+https://` | required | system trust store + (opt) signed git tag | sha256 from index.json + signature; git history advisory |

**Critical invariant unchanged from v1:** every fetched tarball is
re-hashed locally and the publisher signature re-verified. A malicious
or compromised registry can DoS a consumer (404, lie about latest
version, serve stale index) but cannot inject content that passes
v0.1.1 §6 verification. This was the v1 design (registry spec §1
"registry is untrusted") and remains the v2 invariant.

## 6. Breaking-change analysis

| Change                                              | Breaks v1? |
|-----------------------------------------------------|------------|
| New URL schemes accepted by `_resolve_registry_root`| No — additive |
| New env vars / credential file                      | No — opt-in |
| New cache dir under `~/.cache/`                     | No — first run creates it |
| `Registry.__init__` signature                       | No — same `(url: str)` |

Existing code passing `file:///abs/path` keeps working byte-identically.

## 7. Test plan

- `tests/test_https_registry.py`
  - Mock `httpx.Client`; assert correct paths, headers, retry behavior.
  - 404 → empty `list_versions`; 5xx → retried 3×; 401 → no retry.
  - Cache hit returns without HTTP call; sha256 mismatch invalidates
    cache and re-fetches once.
- `tests/test_git_https_registry.py`
  - Run against a temp git repo (file:// transport for git, but
    `git+https://` URL parsing path).
  - First call clones; second within TTL skips clone; after TTL pulls.
  - Pinned ref (`@v0.1.2`) checks out the tag.
- `tests/adversarial/test_d7_transport_lying.py`
  - Registry serves valid index.json but tampered tarball → consumer's
    `verify_pack` rejects. Confirms RegistryError vs VerificationError
    distinction.

Test count target: +12, kept under v1's 90/90 ratio of regression vs
adversarial.

## 8. Open questions

1. **Auth credential lifecycle.** Should `.kb/registry-credentials.yaml`
   support per-namespace tokens, or only per-host? Defer to first
   private-registry deployment for signal.
2. **Proxy support.** Honor `HTTPS_PROXY` env? Yes, pass-through to
   httpx. No special UI.
3. **Large-tarball streaming.** Today `fetch()` reads the whole
   tarball before extracting. >100MB packs are out of scope per
   decision #6 (~5 pages, ~20KB), so leave streaming for later.

## 9. Effort estimate

~600 lines: `transports/https.py` (~250), `transports/git_https.py`
(~150), tests (~200). One iteration; one dogfood report
(`reports/07-phase4-network-dogfood.md`) jointly with RFC-0002.
