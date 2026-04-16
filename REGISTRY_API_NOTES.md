# REGISTRY_API_NOTES.md

Reference snapshot of the public surface of `reference/kb_pack/`,
`reference/kb_registry/`, and the `examples/sample-registry/` layout,
taken at commit `1e1a763` on 2026-04-16.

Source of truth for "public" here is `__init__.py` in each package,
plus the named fail modes each function raises. No code has been
changed; this is a read-only map.

---

## 1. kb_pack

Pack build + verify per AutoEvolve pack spec v0.1.1. `__version__ = "0.1.0"`.

### 1.1 kb_pack.canonical

- `canonical_json(obj: Any) -> bytes`
  - `canonical-2026-04`: UTF-8, sorted keys, no whitespace, `allow_nan=False`.
  - **Raises:** `ValueError` (via `json.dumps`) on NaN/±Infinity or non-serializable input.

### 1.2 kb_pack.did

- `did_to_safe_path(did: str) -> str`
  - Lossy one-way transform `did:web:example.com -> did-web-example.com`.
  - **Raises:** `ValueError` if input does not start with `did:`, or contains NUL, backslash, or any control char (`ord < 0x20`).

### 1.3 kb_pack.merkle

Constants: `EXCLUDED_TOP_LEVEL = {"pack.lock"}`, `EXCLUDED_DIRS = {"signatures"}`, `CONTENT_PREFIXES = ("README.md", "pack.manifest.yaml", "pages/")`.

- `FileEntry` — frozen dataclass with `relative_path: str`, `sha256_hex: str`.
- `collect_pack_entries(pack_root: Path) -> list[FileEntry]`
  - Walks every file under `pack_root` except `pack.lock` and `signatures/**`, returns entries sorted by UTF-8 byte order of relative path.
  - **Raises:** `OSError` on filesystem read failures.
- `compute_roots(pack_root: Path) -> tuple[str, str, list[FileEntry]]`
  - Returns `(content_root_hex, pack_root_hex, entries)`. Roots are bare hex (no `sha256:` prefix).
  - **Raises:** `OSError` on filesystem read failures.

### 1.4 kb_pack.manifest

Constants: `SPEC_VERSION = "autoevolve-pack/0.1.1"`, `REQUIRED_FIELDS = ("spec_version", "pack_id", "version", "namespace", "publisher", "title", "attestations", "policy_surface")`, `REQUIRED_ATTESTATIONS = ("provenance", "redaction", "evaluation", "license")`.

Canonical nested shape of `pack.manifest.yaml` (the only shape `kb_pack.load_manifest` accepts — every downstream tool, including `registry-repo/scripts/validate_pack.py` Check 2, reads fields from these exact locations):

```yaml
spec_version: autoevolve-pack/0.1.1
pack_id: my-team.patterns.circuit-breaker
version: 1.0.0
namespace: my-team.patterns
publisher:
  id: did:web:my-team.example
title: Circuit breaker selection guide
attestations:
  provenance: attestations/provenance.json
  redaction: attestations/redaction.json
  evaluation: attestations/evaluation.json
  license: attestations/license.json
policy_surface: {}           # opaque to kb_pack; shape is pack-defined
license:                     # optional; spec §3 / amendment B5
  spdx: MIT
```

- `publisher.id` is the DID. There is no top-level `publisher_did` field.
- `license.spdx`, when present, is cross-checked against `license.json.license_spdx` at S3c (amendment B5). Absent means "no license declared at the manifest level" — the license attestation is still required.
- `attestations` is a mapping of kind → relative path. Kinds that are not one of the four in `REQUIRED_ATTESTATIONS` fail validation.
- `lock_hash` MUST NOT appear; amendment A2 removed it.

- `ManifestError(ValueError)` — all manifest problems raise this.
- `Manifest` — frozen dataclass wrapping `doc: dict`. Properties: `pack_id`, `version`, `publisher_id`, `spec_version`, `attestation_paths`, `pack_ref` (`"{pack_id}@{version}"`).
- `load_manifest(pack_root: Path) -> Manifest`
  - **Raises:** `ManifestError` when `pack.manifest.yaml` is missing, YAML-unparseable, not a mapping, or fails `validate`.
- `validate(doc: dict[str, Any]) -> None`
  - **Raises:** `ManifestError` on missing required fields, wrong `spec_version`, missing `publisher.id`, `attestations` not a mapping, missing attestation kinds, or presence of (removed) `lock_hash` field.

### 1.5 kb_pack.lock

Constant: `SPEC_HEADER = "autoevolve-pack/0.1.1"`.

- `Lock` — frozen dataclass with `entries: list[FileEntry]`, `content_root: str` (always `"sha256:..."`), `pack_root: str` (always `"sha256:..."`).
- `build_lock_for(pack_root: Path) -> Lock`
  - Thin wrapper around `compute_roots` that re-applies the `sha256:` prefix.
  - **Raises:** `OSError` from filesystem walks.
- `render_lock(lock: Lock) -> str`
  - **Raises:** `ValueError("Lock has no entries; pack directory is empty.")`.
- `write_lock(pack_root: Path, lock: Lock) -> Path`
  - Writes `pack_root/pack.lock`, returns path.
  - **Raises:** `ValueError` (empty lock), `OSError` on write.
- `parse_lock(text: str) -> Lock`
  - **Raises:** `ValueError("pack.lock is missing required fields")` if entries, `content_root`, or `pack_root` are absent.
- `read_lock(pack_root: Path) -> Lock`
  - **Raises:** `FileNotFoundError` / `OSError` when file is missing or unreadable, `ValueError` from `parse_lock`.

### 1.6 kb_pack.signature

Constants: `ALGORITHM = "ed25519"`, `PACK_SIG_PREFIX = b"autoevolve-pack/0.1.1\n"`.

- `make_envelope(key_id: str, value_hex: str) -> dict[str, str]` — builds `{"algorithm": "ed25519", "key_id": ..., "value": ...}`.
- `validate_envelope(envelope: Any) -> None`
  - **Raises:** `ValueError` if not a dict, wrong algorithm, or missing `key_id` / `value`.
- `sign_attestation(attestation: dict, key_id: str, private_key_hex: str) -> dict`
  - Strips any prior `signature`, canonical-JSONs the rest, signs with Ed25519, attaches a fresh envelope. Mutates input and returns it.
  - **Raises:** `ValueError` from hex decoding; cryptography backend exceptions from key loading.
- `verify_attestation_signature(attestation: dict, public_key_hex: str) -> bool`
  - Validates envelope, then verifies canonical JSON bytes of `attestation` minus `signature`.
  - **Raises:** `ValueError` from `validate_envelope` or from invalid hex. Returns `False` on `InvalidSignature`.
- `sign_pack_root(pack_root_hex: str, private_key_hex: str) -> bytes`
  - Signs `b"autoevolve-pack/0.1.1\n" + pack_root_hex.encode("ascii")`.
  - **Raises:** `ValueError` on bad hex, `UnicodeEncodeError` on non-ASCII hex (should never happen for valid hex).
- `verify_pack_root(pack_root_hex: str, signature_bytes: bytes, public_key_hex: str) -> bool`
  - Returns `False` on `InvalidSignature` / `ValueError`.

### 1.7 kb_pack.attestation

Constant: `KINDS = ("provenance", "redaction", "evaluation", "license")`.

- `AttestationError(ValueError)` — kind-specific failures.
- `build_envelope(kind: str, pack_ref: str, content_root: str, issuer: str, issued_at: str | None = None) -> dict`
  - **Raises:** `AttestationError` if `kind` not in `KINDS`.
- `build_provenance(pack_ref: str, content_root: str, issuer: str, source_documents: int, source_types: list[str], build_environment: str = "kbtransfer-v0.1.0", issued_at: str | None = None) -> dict`
  - **Raises:** `AttestationError` (via `build_envelope`).
- `build_redaction(pack_ref: str, content_root: str, issuer: str, redaction_level: str, policy_id: str, policy_version: str, residual_risk_notes: list[str], categories_redacted: list[str] | None = None, human_review: dict | None = None, adversarial_verification: dict | None = None, llm_assisted_by: dict | None = None, issued_at: str | None = None) -> dict`
  - **Raises:** `AttestationError` if `residual_risk_notes` is empty (amendment C1).
- `build_evaluation(pack_ref: str, content_root: str, issuer: str, evaluators: list[dict] | None = None, test_cases: dict | None = None, composite_score: float | None = None, issued_at: str | None = None) -> dict`
  - **Raises:** `AttestationError` (via `build_envelope`).
- `build_license(pack_ref: str, content_root: str, issuer: str, license_spdx: str, license_class: str, grants: list[str] | None = None, restrictions: list[str] | None = None, warranty: str | None = None, issued_at: str | None = None) -> dict`
  - **Raises:** `AttestationError` (via `build_envelope`).
- `write_attestation(path: Path, attestation: dict) -> None`
  - Writes canonical-JSON bytes; creates parent dir.
  - **Raises:** `OSError` on write.
- `load_attestation(path: Path) -> dict`
  - **Raises:** `FileNotFoundError`, `OSError`, `json.JSONDecodeError`.

### 1.8 kb_pack.build

- `BuildError(RuntimeError)`.
- `BuildResult` — frozen dataclass: `pack_root_dir: Path`, `content_root: str`, `pack_root: str`, `attestation_paths: dict[str, Path]`, `signature_path: Path`, `public_key_path: Path`.
- `build_pack(pack_dir: Path, key_id: str, private_key_hex: str, public_key_hex: str) -> BuildResult`
  - Two-phase builder: content_root first, then rewrites each attestation stub with envelope fields + signature, then pack_root + `pack.lock` + `signatures/publisher.sig` + `signatures/publisher.pubkey`.
  - **Raises:**
    - `ManifestError` via `load_manifest`.
    - `BuildError("unknown attestation kind declared in manifest: ...")` if manifest names a non-standard kind.
    - `BuildError(f"missing attestation file: {relpath}")` if a stub is absent.
    - `BuildError("redaction attestation missing non-empty residual_risk_notes (C1)")`.
    - `BuildError("content_root drifted between attestation build and pack_root build; ...")` if content files changed mid-build.
    - `ValueError` from hex decoding keys; `OSError` on file I/O.

### 1.9 Key file format on disk (kb_cli sidecars)

`kb_cli init` writes each Ed25519 keypair as a pair of YAML sidecar files — NOT as raw 32-byte blobs. Downstream tooling that reads these files (the registry's `validate_pack.py`, custom publish scripts, anything rebuilding `keys.json`) must `yaml.safe_load` them, not open them in binary mode.

**Locations** (relative to the KB root):

- `.kb/keys/<key_id>.priv` — mode `0o600`
- `.kb/keys/<key_id>.pub`  — mode `0o644`

where `<key_id>` is assigned by `kb_cli/keygen.py` as `{UTC_date}-{8_hex_chars}` (e.g. `20260416-d57d3101`).

**Schema** of each file (both `.priv` and `.pub` share the same shape; the private file additionally carries `private_key_hex`):

```yaml
key_id: 20260416-d57d3101
publisher_id: did:web:my-team.example
algorithm: ed25519
public_key_hex: 9e3c3d02352c00ea5451feec93751dfe97b05e390a4d94123a376b7e4bd7a731
# .priv file only:
private_key_hex: <64 hex chars — 32 raw bytes>
created_at: 2026-04-16T09:18:07Z
```

`public_key_hex` and `private_key_hex` are lowercase hex of the raw 32-byte Ed25519 key material (`serialization.Encoding.Raw` + `PrivateFormat.Raw`). Note that `algorithm` here is the lowercase `ed25519` used by kb_pack internally — the registry's `keys.json` uses the capitalized form `Ed25519` as its algorithm identifier.

**Converting to the registry's `keys.json`** shape (see REGISTRY_POLICY.md §4):

```python
import base64
import yaml

pub_doc = yaml.safe_load(open(".kb/keys/20260416-d57d3101.pub"))
pub_bytes = bytes.fromhex(pub_doc["public_key_hex"])
pub_b64   = base64.b64encode(pub_bytes).decode("ascii")

keys_json = {
    "did": pub_doc["publisher_id"],
    "keys": [
        {
            "key_id":          pub_doc["key_id"],
            "algorithm":       "Ed25519",          # capital E
            "public_key_b64":  pub_b64,            # 44-char b64
        }
    ],
}
```

The `public_key_b64` result is 44 characters including the trailing `=` padding (`base64.b64encode` of 32 bytes always yields 44 chars).

### 1.10 kb_pack.verify

- `VerificationResult` — dataclass: `ok: bool`, `step: str`, `message: str`, `content_root: str | None`, `pack_root: str | None`, `attestations: dict[str, dict] | None`.
- `PublisherKeyResolver`
  - `__init__(entries: dict[tuple[str, str], str] | None = None)`.
  - `register(publisher_id: str, key_id: str, public_key_hex: str) -> None`.
  - `lookup(publisher_id: str, key_id: str) -> str | None`.
- `verify_pack(pack_dir: Path, resolver: PublisherKeyResolver) -> VerificationResult`
  - Executes S2, S3a, S3b, S3c, S5 per spec v0.1.1 §6.2.
  - Does **not** raise on verification failure — returns `VerificationResult(ok=False, step=..., message=...)`. Step codes: `S2`, `S3a`, `S3b`, `S3c`, `S5`.
  - Success returns `step="S7"`, `message="verified"`, and populates `content_root` / `pack_root` / `attestations`.

### 1.11 kb_pack.dependency

Constants: `DEFAULT_MAX_DEPTH = 8`, `DEFAULT_MAX_INHERIT_DEPTH = 2`.

- `RecursiveVerificationResult` — dataclass: `ok: bool`, `step: str`, `message: str`, `breadcrumb: list[str]`, `visited: dict[str, VerificationResult]`.
  - Helper: `breadcrumb_text() -> str` joins the trail with `" -> "`.
- `verify_with_dependencies(pack_dir: Path, resolver: PublisherKeyResolver, registry: Registry | None, policy: dict[str, Any], *, breadcrumb: list[str] | None = None, visited: dict[str, VerificationResult] | None = None, depth: int = 0, inherit_depth: int = 0) -> RecursiveVerificationResult`
  - Runs `verify_pack` on root, then resolves + fetches + recursively verifies each `dependencies[]` entry per `consumer.trust_inheritance` mode (`strict`, `inherit-from-parent`, `namespace-scoped`).
  - Does **not** raise on verification failure; returns a failure result with a breadcrumb. Step codes emitted here: `max_dependency_depth`, `manifest_invalid`, `cycle`, `dependencies_malformed`, `dep_malformed`, `dep_missing_pack_id`, `dep_resolve_failed`, `dep_manifest_invalid`, `dep_missing_pubkey`, `untrusted_dep_publisher`, `inherit_depth_exceeded`, `namespace_publisher_rejected`, `unknown_trust_inheritance_mode`, plus any step from the underlying `verify_pack`.
  - **Raises** `RegistryError` only when a dep lists neither a `registry_hint` nor can fall back on the supplied default registry.

### 1.12 Top-level `kb_pack` `__all__`

Re-exports everything above (see `reference/kb_pack/__init__.py:63-108`): `ALGORITHM`, `ATTESTATION_KINDS`, `AttestationError`, `BuildError`, `BuildResult`, `DEFAULT_MAX_DEPTH`, `DEFAULT_MAX_INHERIT_DEPTH`, `RecursiveVerificationResult`, `verify_with_dependencies`, `FileEntry`, `Lock`, `Manifest`, `ManifestError`, `PublisherKeyResolver`, `REQUIRED_ATTESTATIONS`, `REQUIRED_FIELDS`, `SPEC_VERSION`, `VerificationResult`, plus the `build_*`, `sign_*`, `verify_*`, `load_*`, `write_*`, `parse_lock`, `read_lock`, `render_lock`, `canonical_json`, `did_to_safe_path`, `collect_pack_entries`, `compute_roots`, `make_envelope`, `validate`, `validate_envelope`, `build_pack` functions.

---

## 2. kb_registry

Git-based registry tooling and CI verification. `__version__ = "0.1.0"`.

### 2.1 kb_registry.semver

- `Version` — frozen, ordered dataclass: `major: int`, `minor: int`, `patch: int`.
  - `classmethod Version.parse(text: str) -> Version` — **raises** `ValueError("invalid version: ...")` on anything other than `^\d+\.\d+\.\d+$`.
  - `__str__()` returns `"major.minor.patch"`.
- `matches(version: str, constraint: str) -> bool`
  - Supports `*`, exact (`"1.2.3"` or `"=1.2.3"`), `^`, `~`, `>=`.
  - **Raises:** `ValueError` from `Version.parse` or `"unknown constraint operator: ..."`.
- `highest_matching(versions: list[str], constraint: str) -> str | None`
  - Returns the highest matching version as a string, or `None`.
  - **Raises:** `ValueError` from the underlying parse/matches calls.

### 2.2 kb_registry.index

Constant: `INDEX_VERSION = "kbtransfer-registry/0.1"`.

- `build_index(registry_root: Path) -> dict`
  - Walks `publishers/*/keys.json` and `packs/*/*.tar`, returns a dict with `registry_version`, `updated_at`, `publishers`, `packs`.
  - Swallows `json.JSONDecodeError`, `tarfile.TarError`, `OSError`, `yaml.YAMLError` per entry (skips malformed inputs).
- `write_index(registry_root: Path, index: dict | None = None) -> Path`
  - Writes `registry_root/index.json` (indent=2). Returns the path.
  - **Raises:** `OSError` on write failure.
- `read_index(registry_root: Path) -> dict`
  - If `index.json` exists, returns its parsed JSON; otherwise rebuilds via `build_index`.
  - **Raises:** `json.JSONDecodeError` on a corrupt `index.json`.

### 2.3 kb_registry.registry

- `RegistryError(RuntimeError)` — every registry-layer failure raises this.
- `ResolveResult` — frozen dataclass: `pack_id: str`, `version: str`, `publisher_id: str`, `tar_relative_path: str`, `sha256: str`.
- `Registry(url: str)` — filesystem-backed reader.
  - **Constructor raises:** `RegistryError(f"filesystem registry expected file:// or bare path, got {scheme!r}")` for non-`file`/non-bare URLs; `RegistryError(f"registry root not found: {self.root}")` if the path doesn't exist.
  - `describe() -> dict` — returns `{"url", "registry_version", "publisher_count", "pack_count", "updated_at"}`.
  - `list_versions(pack_id: str) -> list[str]` — sorted lexicographic list, `[]` if unknown.
  - `resolve(pack_id: str, constraint: str = "*") -> ResolveResult`
    - **Raises:** `RegistryError(f"pack_id {pack_id!r} not found")`, `RegistryError(f"no version of {pack_id!r} satisfies {constraint!r}")`, plus propagates `ValueError` from the semver matcher.
  - `fetch(pack_id: str, version: str, dest: Path) -> Path`
    - Extracts the tarball (`filter="data"` on 3.12+) into `dest` and returns the single top-level directory.
    - **Raises:** `RegistryError` on missing tarball file, `RegistryError("tarball did not contain a single top-level directory")` if the archive shape is wrong, plus `tarfile.TarError` / `OSError` on extraction failures.
  - `publisher_keys(publisher_id: str) -> list[dict]` — `[]` if unknown; **raises** `json.JSONDecodeError` on a corrupt keys.json.
  - `search(query: str, limit: int = 20) -> list[dict]` — substring match over pack_id + title + summary + namespace + license_spdx + publisher_id.
  - `rebuild_index() -> Path` — writes `index.json` on disk, returns the path.
- `HttpsRegistry(url: str, *, timeout: float = 30.0, max_bytes: int = 256 * 1024 * 1024)` — HTTPS / `git+https` reader; subclass of `Registry` but does **not** invoke its `__init__` (no filesystem root required).
  - **Constructor raises:** `RegistryError` if scheme is neither `https` nor `git+https`, or if the URL has no host.
  - `_http_get(url: str) -> bytes` — enforces `max_bytes` cap; **raises** `RegistryError` on `URLError`/`HTTPError`/oversize.
  - `_fetch_bytes(rel_path: str, *, expected_sha256: str | None = None) -> bytes`
    - Rejects absolute URLs, traversal (`..`), and empty paths.
    - **Raises:** `RegistryError(f"unsafe registry path: {rel_path!r}")`, `RegistryError(f"path traversal rejected: {rel_path!r}")`, `RegistryError(f"sha256 mismatch for {url!r}: expected ..., got ...")`, plus any `RegistryError` from `_http_get`.
  - `fetch(pack_id, version, dest)` — same signature as `Registry.fetch`, but pulls the tarball over HTTPS with mandatory sha256 verification. **Raises:** `RegistryError("index entry for ... has no sha256; refusing to fetch unverified content over HTTPS")`, plus `RegistryError("tarball did not contain a single top-level directory")`.
  - `publisher_keys(publisher_id)` — fetches `keys.json` over HTTPS; `[]` if unknown. **Raises:** `RegistryError` from the HTTPS layer, `json.JSONDecodeError` on malformed JSON.
  - `rebuild_index()` — **always raises** `RegistryError("HTTPS registries are read-only; rebuild at the source and redeploy")`.
  - `submit(tarball_path: Path, *, notes: str = "", bearer_token: str | None = None) -> dict` (RFC-0002 submit path)
    - POSTs a multipart form to `{base}/v0.1/submit`; invalidates the local index cache on success.
    - **Raises:** `RegistryError` if the tarball is missing, exceeds `max_bytes`, the request fails at the `URLError` layer, or the response is not valid JSON / not a JSON object. HTTP 4xx responses are **not** raised — their JSON body is returned so the caller can inspect structured errors.
- `open_registry(url: str) -> Registry`
  - Dispatches by scheme: `https` / `git+https` → `HttpsRegistry`; everything else → `Registry` (which itself rejects non-file URLs).

### 2.4 Top-level `kb_registry` `__all__`

`INDEX_VERSION`, `HttpsRegistry`, `Registry`, `RegistryError`, `ResolveResult`, `Version`, `build_index`, `highest_matching`, `matches`, `open_registry`, `read_index`, `write_index`.

---

## 3. examples/sample-registry/

Reference layout for a GitHub-hosted kb-registry. The trust model the README states: the registry is not a trust root — consumers verify each pack locally against the publisher keys published under `publishers/<did-safe>/keys.json`.

### 3.1 Directory tree

```
examples/sample-registry/
├── README.md
├── .github/
│   └── workflows/
│       └── verify-pack.yml
├── packs/
│   └── .gitkeep
├── publishers/
│   └── .gitkeep
└── scripts/
    └── verify_submission.py
```

### 3.2 File-by-file

- `README.md` — Describes the layout, consumer-side `kb/registry_*` / `kb/subscribe/0.1` tool calls (with `file://`, `https://`, `git+https://` schemes), publisher submission flow (add `publishers/<did-safe>/keys.json`, drop tarball in `packs/<pack_id>/<version>.tar`, open PR), and the trust model disclaimer.
- `.github/workflows/verify-pack.yml` — GitHub Actions workflow triggered by PRs touching `packs/**` or `publishers/**` (and `workflow_dispatch`); checks out the registry with LFS, checks out `your-org/KBTRANSFER@main`, pip-installs `kb_pack`, diffs `packs/**/*.tar` against the base branch, feeds each changed path as `--pack` to `scripts/verify_submission.py`, and on success regenerates `index.json` via `kb_registry.write_index`.
- `packs/.gitkeep` — Empty placeholder so the directory survives `git init`; actual pack tarballs live at `packs/<pack_id>/<version>.tar`.
- `publishers/.gitkeep` — Empty placeholder; actual publisher trust anchors live at `publishers/<did-safe>/keys.json`.
- `scripts/verify_submission.py` — Standalone pre-merge verifier. Takes `registry_root` positional arg and repeatable `--pack <relative-path>` options; defaults to every `packs/**/*.tar` under the root. Builds a `PublisherKeyResolver` from `publishers/<did-safe>/keys.json` (filters to `algorithm == "ed25519"`), extracts each tarball into a tempdir, runs `kb_pack.verify_pack`, prints `OK <pack_ref> (<tar>)` or `FAIL [<step>] <pack_ref>: <msg>`, and exits non-zero if any pack fails. Exit codes: `0` (success or no tarballs), `1` (at least one verification failure), `2` (registry root not found or `kb_pack` import failure).
