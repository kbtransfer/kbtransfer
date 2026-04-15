# examples/sample-registry-http/

FastAPI front for a KBTRANSFER kb-registry. Implements RFC-0002
`POST /v0.1/submit` plus the read endpoints `HttpsRegistry` consumes.

## Quick start

```bash
export KBTRANSFER_REGISTRY_ROOT=$PWD/data
mkdir -p "$KBTRANSFER_REGISTRY_ROOT/packs" "$KBTRANSFER_REGISTRY_ROOT/publishers"

pip install -e ".[server]"
uvicorn examples.sample-registry-http.app:app --reload
```

Or via Docker:

```bash
docker compose -f examples/sample-registry-http/docker-compose.yml up --build
```

## Layout on disk

The HTTP front reuses the filesystem-layout a git-hosted registry
uses (see `examples/sample-registry/README.md`). The process is
expected to own the tree rooted at `KBTRANSFER_REGISTRY_ROOT`:

```
<root>/
├── publishers/<did-safe>/keys.json     operator-provisioned
├── packs/<pack_id>/<version>.tar       written on accept (auto mode)
├── submissions/<pack_id>/<version>.tar.pending   written on accept (stage mode)
└── index.json                          regenerated after each accepted submit
```

## Modes

- **auto** (default) — accepted submissions are immediately written
  into `packs/` and `index.json` is rebuilt in-place. Good for open
  registries and CI pipelines.
- **stage** — accepted submissions land under `submissions/` with a
  `.pending` suffix. A human operator reviews, moves the file to
  `packs/<pack_id>/<version>.tar`, and rebuilds the index (e.g. via
  `python -c "from kb_registry import write_index; write_index(...)"`).
  Good for curated registries that preserve PR review but still want
  a wire upload endpoint.

Flip modes with `KBTRANSFER_COMMIT_MODE=auto|stage`.

## Trust roles

| Role        | Auth                                       | Rejection before sig check           |
|-------------|--------------------------------------------|--------------------------------------|
| open        | publisher's pack signature                 | none — publisher-controlled          |
| consortium  | pack signature + allowlist match           | `publisher_admitted`                 |
| private     | pack signature + bearer token + allowlist  | `bearer_token`, `publisher_admitted` |

Set with `KBTRANSFER_TRUST_ROLE=open|consortium|private`. For
consortium/private, populate `KBTRANSFER_ALLOWLIST` with the
comma-separated publisher DIDs. For private, also populate
`KBTRANSFER_BEARER_TOKENS` with accepted tokens; clients must set
`Authorization: Bearer <token>`.

## What this server does NOT do

- **No trust anchor:** consumers of this registry independently
  verify each pack they fetch against the publisher's public keys.
  A malicious or buggy registry cannot promote untrusted content.
- **No publisher self-registration:** until RFC-0003 (did:web:
  resolution) ships, publishers cannot submit their first key via
  this endpoint. The operator installs `publishers/<did-safe>/keys.json`
  out-of-band. Open tier registries document this as a known Phase 4
  limitation.
- **No TLS termination:** run behind nginx / Caddy / a cloud LB.
  `HttpsRegistry` requires the public URL to be https, so the LB
  MUST present a valid certificate.
