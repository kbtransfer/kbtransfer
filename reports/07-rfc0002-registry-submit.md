# Report 07 — RFC-0002 `registry/submit/0.1` shipping + Phase 4 close

**Date:** 2026-04-15
**Scope:** Phase-gate dogfood for RFC-0002. End-to-end over FastAPI
TestClient, local fixture publishers, real `HttpsRegistry` wire
encoding (multipart + bearer), real `verify_pack` on the server.
**Outcome:** Phase 4 is closed. Transport (RFC-0001) + submit
(RFC-0002) both in `status: shipped`. Roadmap promotes to Phase 5.

---

## 1. What shipped

Five landable artifacts, one themed commit:

| Artifact                                         | Rough size |
|--------------------------------------------------|-----------|
| `reference/kb_registry_server/`                  | ~320 LOC  |
| `examples/sample-registry-http/` (FastAPI + docker) | ~260 LOC  |
| `HttpsRegistry.submit()` + `kb/registry_submit/0.1` | ~170 LOC  |
| `kb/publish/0.1` gained `submit_to_registry`     | ~60 LOC   |
| `tests/` additions (3 files, 27 tests)           | ~430 LOC  |

Library is stdlib-only. FastAPI stays in the `examples/` tree and
behind the optional `server` extras install (`pip install -e .[server]`).

## 2. Wire-level flow

1. Publisher runs `kb/publish/0.1` with
   `submit_to_registry: https://registry.example.com`.
2. Local build produces `published/<pack_id>-<version>.tar` as before.
3. `kb_publish` delegates to `HttpsRegistry.submit(tarball, …)`.
4. Client POSTs `multipart/form-data` with a `tarball` file field (plus
   optional `notes` + `Authorization: Bearer <token>`) to
   `/v0.1/submit`.
5. FastAPI shim reads the body into memory, calls
   `RegistryServer.submit(tar_bytes, bearer_token=…, notes=…)`.
6. `validate_submission_bytes` runs the full 10-check list (see §3);
   on failure, returns HTTP 400 with `{accepted: false, errors: […]}`.
7. On pass, `_commit_submission` writes the tarball through a single
   `O_CREAT | O_EXCL` `os.open`; concurrent replays lose cleanly
   with `version_uniqueness`.
8. Index is rebuilt in auto mode (`write_index`); stage mode drops a
   `.pending` file for a human operator to promote.
9. Client response body includes `accepted`, `pack_id`, `version`,
   `canonical_path` (relative), `checks_passed` (deterministic list),
   `received_at` (ISO UTC), `commit_mode`.

## 3. Check pipeline (stable `CHECK_NAMES` tuple)

```
size_limit
tar_safe_extract
manifest_parse
publisher_admitted          (consortium / private only)
publisher_keys_known
content_root_recompute
signature_verify
attestations_present
residual_risk_notes_nonempty
version_uniqueness
```

Mapping: each name corresponds 1:1 to an error `check` code the
wire can emit. `content_root_recompute`, `signature_verify`,
`attestations_present`, and `residual_risk_notes_nonempty` are
mirrors of `verify_pack`'s S2/S3a/S3b/S3c/S5 — see
`_map_verify_step_to_check` in `kb_registry_server/validation.py`.

## 4. Auth matrix

| Trust role  | Fails before sig check          | Fails if sig invalid |
|-------------|---------------------------------|----------------------|
| `open`      | (nothing)                       | `signature_verify`   |
| `consortium`| `publisher_admitted` if not on allowlist | `signature_verify` |
| `private`   | `bearer_token` if header missing/bad, then `publisher_admitted` | `signature_verify` |

Private tier MUST configure at least one bearer token; the dataclass
rejects that at construction time. Consortium tier silently treats an
empty allowlist as "admit nobody", which is correct-by-default.

## 5. Failure modes exercised

| Failure                                    | Test                                          |
|--------------------------------------------|-----------------------------------------------|
| Oversize (library path)                    | `test_d8_03_oversize_rejected_before_extract` |
| Absolute-path tarball entry                | `test_d8_01_path_traversal_absolute_rejected_before_extract` |
| Parent-ref tarball entry                   | `test_d8_02_path_traversal_parent_ref_rejected` |
| Multi-top-level tarball                    | `test_d8_04_multiple_top_level_dirs_rejected` |
| Non-tar bytes                              | `test_d8_05_non_tar_bytes_rejected_as_tar_safe_extract` |
| Replay (same version twice)                | `test_d8_06_replay_submit_is_rejected_as_duplicate` |
| Unknown publisher                          | `test_validate_rejects_unknown_publisher`     |
| Consortium non-allowlisted                 | `test_validate_rejects_consortium_non_allowlisted_publisher` |
| Tampered content after signing             | `test_validate_rejects_tampered_signature`    |
| Duplicate version (via library)            | `test_validate_rejects_duplicate_version`     |
| Private tier missing/wrong/correct token   | `test_private_tier_requires_bearer_token`     |
| HTTP layer 400 body shape                  | `test_http_submit_rejects_bad_pack_with_structured_errors` |

Each rejection leaves the registry tree untouched (asserted in
`test_registry_server_submit_returns_structured_error`). No rejected
bytes are ever stored.

## 6. What remains manual vs automated

**Automated in this commit:**
- Submit → validate → commit → index-rebuild (auto mode).
- Submit → validate → stage (stage mode).
- Round-trip `publish → submit → resolve → fetch → extract` over
  the FastAPI wire.

**Still manual:**
- **First-time publisher keys.** Until RFC-0003 (did:web: resolution)
  lands, the operator must drop `publishers/<did-safe>/keys.json`
  before a new publisher's first submit. `publisher_keys_known`
  fires otherwise. This is documented in
  `examples/sample-registry-http/README.md` §"What this server does NOT do".
- **Registry attestation in response.** RFC-0002 §3.2 sketches a
  `registry_attestation` with its own Ed25519 signature, gated on
  RFC-0003 (so the registry's DID is resolvable the same way a
  publisher's is). Shipped response carries `checks_passed` + ISO
  timestamp as a structured receipt; the signed-receipt layer is
  deferred to Phase 5.
- **TLS termination.** `HttpsRegistry` refuses `http://`; the
  FastAPI app stays HTTP-only and expects a reverse proxy in front
  (documented in the README).

## 7. Honest limits

- **In-memory upload.** The server reads the full tarball into RAM
  before validating. Pattern-granularity packs (spec decision #6,
  ~5 pages) stay well under the 256 MiB default; a future streaming
  upload path would be needed if pack size grows.
- **No per-publisher rate limits.** RFC-0002 §2 bullet 3
  intentionally defers these. Operators layer them at nginx / Caddy.
- **No yank.** Registry spec §3.4 sketches yanking; not in this
  shipping. Will become RFC-0002a if needed before Phase 6.
- **Async 202 submit.** RFC-0002 §10 open question #1. Still
  deferred — no oversize-pack incident yet.
- **Repacker skipping content:** the tar extraction filter defaults
  to `data` on Python 3.14 + extended attributes; symlinks are
  rejected by that filter. Consistent with the consumer-side
  extraction in `HttpsRegistry.fetch` (same filter).

## 8. Test-suite delta

- Was: 170 passing + 4 skipped (end of commit `0a19b6f`).
- Now: **197 passing + 4 skipped.** `+27 tests` across three files:
  - `tests/test_registry_submit.py` (15)
  - `tests/adversarial/test_d8_submit_abuse.py` (6)
  - `tests/test_sample_registry_http.py` (6)
- Runtime on a cold Python 3.14 venv: ~2.5s for the full suite.

## 9. Phase 4 gate

Gate text from `ROADMAP-v2.md` §"Phase 4":

> `examples/sample-registry/` demo runs end-to-end against a hosted
> instance — submit → verify → fetch — without touching git.

Met in `test_http_submit_round_trip_publish_fetch_verify`:

1. `_build_pack` runs the full `kb/draft_pack → kb/distill →
   kb/publish` pipeline in a scratch KB and produces a signed
   tarball.
2. `_install_publisher_keys` drops the publisher's Ed25519 key into
   the registry's `publishers/<did-safe>/keys.json`.
3. `_TestClientHttpsRegistry(client).submit(tar_path)` posts the
   tarball to `POST /v0.1/submit`; the FastAPI app validates +
   commits + rebuilds the index. `response.accepted == True`.
4. `reg.resolve("http.roundtrip", "^1.0")` reads the freshly
   rebuilt `/index.json` and returns version `1.0.0`.
5. `reg.fetch("http.roundtrip", "1.0.0", consumer_dir)` downloads
   the tarball, verifies `sha256` against `index.json`, and extracts
   to the consumer. `pack.manifest.yaml` and
   `signatures/publisher.sig` are present.

Zero git operations. Gate closed.

## 10. What's next

- **Phase 5 opens.** RFC-0003 (did:web: resolution) + RFC-0004
  (RFC 3161 timestamping) are the remaining Phase 5 items. Both
  still `status: draft`.
- **AEAI integration.** With this shipping, AEAI's `push_to_peer_kb`
  gets a sibling `push_to_https_registry` handler in its own
  repo — roughly 20 lines, calling the new
  `kb/registry_submit/0.1` MCP tool. Tracked in the AEAI session,
  not this repo.
- **Backlog continues** per `memory/aeai_backlog_2026_04_15.md`:
  next up is dogfood follow-up #5 (unsubscribe on read-only
  subscriptions), then the handler-set commit (#3/#4/#6/#7).

## 11. Files touched

```
pyproject.toml                                             (+optional deps, +1 package)
reference/kb_registry_server/__init__.py                   (new)
reference/kb_registry_server/validation.py                 (new)
reference/kb_registry_server/server.py                     (new)
reference/kb_registry/registry.py                          (+submit method + multipart builder)
reference/kb_mcp_server/tools/registry_submit.py           (new)
reference/kb_mcp_server/tools/publish.py                   (+submit_to_registry)
reference/kb_mcp_server/tools/__init__.py                  (+registry_submit)
examples/sample-registry-http/app.py                       (new)
examples/sample-registry-http/Dockerfile                   (new)
examples/sample-registry-http/docker-compose.yml           (new)
examples/sample-registry-http/README.md                    (new)
tests/test_registry_submit.py                              (new)
tests/test_sample_registry_http.py                         (new)
tests/adversarial/test_d8_submit_abuse.py                  (new)
rfcs/0002-registry-submit.md                               (status → shipped, +shipped_at)
ROADMAP-v2.md                                              (+status column, gate pointer)
reports/07-rfc0002-registry-submit.md                      (this file)
```

## 12. Pointer for future readers

If you're standing up a real `kb-registry` deployment after reading
this report:

- Start from `examples/sample-registry-http/README.md`; it's the
  thin layer most operators touch.
- For the actual validation logic, read
  `reference/kb_registry_server/validation.py` — this is what
  determines what passes and what does not.
- For the wire format, `POST /v0.1/submit` as documented in
  `rfcs/0002-registry-submit.md` §3.1 is normative. Deploy-specific
  additions (rate limits, per-publisher quotas) go in the reverse
  proxy, not the app.
