"""End-to-end pack build per spec v0.1.1 §4 + §5.

Input: a directory that already contains a valid `pack.manifest.yaml`,
a `README.md`, content under `pages/`, and the four attestation stubs
under `attestations/`. Each stub is a JSON object that supplies the
kind-specific body fields; the builder fills in the common envelope
(content_root, issued_at if missing, signature) as part of the build.

Output (in the same directory):
    - `pack.lock` with two merkle roots.
    - `attestations/{kind}.json` rewritten with content_root binding
      and envelope signature.
    - `signatures/publisher.sig` (raw 64-byte signature over
      `"autoevolve-pack/0.1.1\\n" || pack_root_hex`).
    - `signatures/publisher.pubkey` (raw 32-byte Ed25519 public key).

The builder does NOT run the distiller; it assumes the content and
attestation stubs are already redacted and compliant. Callers use
`kb_distiller` upstream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kb_pack.attestation import KINDS, write_attestation
from kb_pack.lock import build_lock_for, write_lock
from kb_pack.manifest import load_manifest
from kb_pack.merkle import compute_roots
from kb_pack.signature import sign_attestation, sign_pack_root


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    pack_root_dir: Path
    content_root: str
    pack_root: str
    attestation_paths: dict[str, Path]
    signature_path: Path
    public_key_path: Path


def _inject_common_fields(
    attestation: dict[str, Any],
    kind: str,
    pack_ref: str,
    content_root: str,
    issuer: str,
) -> None:
    """Overwrite or fill the required envelope fields per spec §5.1/A1."""
    attestation["spec"] = f"autoevolve-attestation/{kind}/0.1.1"
    attestation["pack"] = pack_ref
    attestation["content_root"] = (
        content_root if content_root.startswith("sha256:") else f"sha256:{content_root}"
    )
    attestation["issuer"] = issuer


def build_pack(
    pack_dir: Path,
    key_id: str,
    private_key_hex: str,
    public_key_hex: str,
) -> BuildResult:
    """Build the pack in-place. Overwrites pack.lock, signatures/*, and
    any signature fields on the attestation stubs."""
    pack_dir = pack_dir.resolve()
    manifest = load_manifest(pack_dir)

    # Phase 1 of the two-merkle scheme: content_root depends only on
    # content files (manifest + README + pages), so we can compute it
    # before we touch the attestations.
    content_root_hex, _pre_pack_root, _ = compute_roots(pack_dir)
    content_root = f"sha256:{content_root_hex}"

    # Inject the common envelope fields into each stub and sign.
    attestation_paths: dict[str, Path] = {}
    for kind, relpath in manifest.attestation_paths.items():
        if kind not in KINDS:
            raise BuildError(f"unknown attestation kind declared in manifest: {kind}")
        att_path = pack_dir / relpath
        if not att_path.is_file():
            raise BuildError(f"missing attestation file: {relpath}")
        data = json.loads(att_path.read_text(encoding="utf-8"))
        _inject_common_fields(data, kind, manifest.pack_ref, content_root, manifest.publisher_id)
        if kind == "redaction":
            notes = data.get("residual_risk_notes")
            if not isinstance(notes, list) or not notes:
                raise BuildError(
                    "redaction attestation missing non-empty residual_risk_notes (C1)"
                )
        data.pop("signature", None)
        sign_attestation(data, key_id=key_id, private_key_hex=private_key_hex)
        write_attestation(att_path, data)
        attestation_paths[kind] = att_path

    # Phase 2: now that attestations are final, compute pack_root and
    # build the lock.
    lock = build_lock_for(pack_dir)
    if lock.content_root != content_root:
        raise BuildError(
            "content_root drifted between attestation build and pack_root build; "
            "did something touch content files mid-build?"
        )
    write_lock(pack_dir, lock)

    # Publisher signature over "autoevolve-pack/0.1.1\n" || pack_root_hex.
    # The spec specifies the bare hex form (no sha256: prefix) as the
    # signing payload suffix.
    signatures_dir = pack_dir / "signatures"
    signatures_dir.mkdir(parents=True, exist_ok=True)
    pack_root_hex = lock.pack_root.removeprefix("sha256:")
    signature_bytes = sign_pack_root(pack_root_hex, private_key_hex)
    signature_path = signatures_dir / "publisher.sig"
    signature_path.write_bytes(signature_bytes)
    public_key_path = signatures_dir / "publisher.pubkey"
    public_key_path.write_bytes(bytes.fromhex(public_key_hex))

    return BuildResult(
        pack_root_dir=pack_dir,
        content_root=lock.content_root,
        pack_root=lock.pack_root,
        attestation_paths=attestation_paths,
        signature_path=signature_path,
        public_key_path=public_key_path,
    )
