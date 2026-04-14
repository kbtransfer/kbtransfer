"""7-step pack verification per spec v0.1.1 §6.2.

Consumer obtains a pack (tarball or directory). For each step the
consumer can halt with the listed failure code; higher-numbered
steps are more specific and typically catch attackers with more
capabilities (see the defense-in-depth hierarchy documented in
reports/02-v0.1.1-dogfood-report.md).

Step map:

    S1  — Fetch                (caller responsibility; not in this file)
    S2  — Verify content_root  (recompute vs pack.lock)
    S3a — Verify attestation bindings (content_root match + files exist)
    S3b — Verify attestation signatures (envelope + hex + key_id)
    S3c — Verify attestation semantics (C1 residual_risk_notes, B5)
    S4  — Consumer policy      (caller; evaluate via policy engine)
    S5  — Verify publisher signature over pack_root
    S6  — Resolve dependencies (Phase 3)
    S7  — Ingest + record      (caller)

Dependency resolution (S6) is deferred to Phase 3 alongside the
trust_inheritance policy. Policy evaluation (S4) is left to the
caller so that the verifier itself stays a pure cryptographic check.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kb_pack.attestation import KINDS, load_attestation
from kb_pack.lock import Lock, read_lock
from kb_pack.manifest import load_manifest
from kb_pack.merkle import compute_roots
from kb_pack.signature import (
    ALGORITHM,
    validate_envelope,
    verify_attestation_signature,
    verify_pack_root,
)


@dataclass
class VerificationResult:
    ok: bool
    step: str
    message: str
    content_root: str | None = None
    pack_root: str | None = None
    attestations: dict[str, dict[str, Any]] | None = None


def _fail(step: str, message: str) -> VerificationResult:
    return VerificationResult(ok=False, step=step, message=message)


def _strip_prefix(value: str) -> str:
    return value.removeprefix("sha256:")


class PublisherKeyResolver:
    """Minimal pluggable lookup from (publisher_id, key_id) -> public_key_hex.

    Phase 2 callers construct one from the trust-store.yaml plus the
    key bundled alongside the pack. Phase 3 will extend this with
    registry-mediated resolution.
    """

    def __init__(self, entries: dict[tuple[str, str], str] | None = None) -> None:
        self._entries: dict[tuple[str, str], str] = dict(entries or {})

    def register(self, publisher_id: str, key_id: str, public_key_hex: str) -> None:
        self._entries[(publisher_id, key_id)] = public_key_hex

    def lookup(self, publisher_id: str, key_id: str) -> str | None:
        return self._entries.get((publisher_id, key_id))


def verify_pack(
    pack_dir: Path,
    resolver: PublisherKeyResolver,
) -> VerificationResult:
    pack_dir = pack_dir.resolve()

    # S2 — recompute content_root and pack_root, cross-check with pack.lock
    try:
        lock: Lock = read_lock(pack_dir)
    except Exception as exc:
        return _fail("S2", f"pack.lock unreadable: {exc}")

    computed_content, computed_pack, _entries = compute_roots(pack_dir)
    if f"sha256:{computed_content}" != lock.content_root:
        return _fail("S2", "content_root in pack.lock does not match recomputed value")
    if f"sha256:{computed_pack}" != lock.pack_root:
        return _fail("S2", "pack_root in pack.lock does not match recomputed value")

    # Load manifest after content_root verified; manifest is part of content.
    try:
        manifest = load_manifest(pack_dir)
    except Exception as exc:
        return _fail("S3a", f"manifest invalid: {exc}")

    # S3a / S3b — attestations
    attestations: dict[str, dict[str, Any]] = {}
    for kind in KINDS:
        relpath = manifest.attestation_paths.get(kind)
        if not relpath:
            return _fail("S3a", f"manifest missing attestation kind {kind!r}")
        att_path = pack_dir / relpath
        if not att_path.is_file():
            return _fail("S3a", f"attestation file not found: {relpath}")
        try:
            data = load_attestation(att_path)
        except Exception as exc:
            return _fail("S3a", f"attestation {kind} parse error: {exc}")

        if data.get("content_root", "") != lock.content_root:
            return _fail(
                "S3a",
                f"attestation {kind} content_root does not match pack.lock",
            )
        if data.get("pack", "") != manifest.pack_ref:
            return _fail(
                "S3a",
                f"attestation {kind} pack reference {data.get('pack')!r} "
                f"does not match manifest {manifest.pack_ref!r}",
            )

        envelope = data.get("signature")
        try:
            validate_envelope(envelope)
        except ValueError as exc:
            return _fail("S3b", f"attestation {kind} envelope invalid: {exc}")
        if envelope["algorithm"] != ALGORITHM:
            return _fail(
                "S3b",
                f"attestation {kind} uses unsupported algorithm "
                f"{envelope['algorithm']!r}",
            )
        public_key_hex = resolver.lookup(manifest.publisher_id, envelope["key_id"])
        if public_key_hex is None:
            return _fail(
                "S3b",
                f"untrusted issuer/key_id: {manifest.publisher_id}/{envelope['key_id']}",
            )
        if not verify_attestation_signature(data, public_key_hex):
            return _fail("S3b", f"attestation {kind} signature did not verify")
        attestations[kind] = data

    # S3c — semantic checks (C1, B5 reclassified as integrity sanity)
    redaction = attestations["redaction"]
    notes = redaction.get("residual_risk_notes")
    if not isinstance(notes, list) or not notes:
        return _fail("S3c", "redaction.residual_risk_notes is missing or empty (C1)")
    license_doc = attestations["license"]
    manifest_license_spdx = (manifest.doc.get("license") or {}).get("spdx")
    if manifest_license_spdx and manifest_license_spdx != license_doc.get("license_spdx"):
        return _fail(
            "S3c",
            f"manifest.license.spdx {manifest_license_spdx!r} != "
            f"license.json.license_spdx {license_doc.get('license_spdx')!r} (B5)",
        )

    # S5 — publisher signature over pack_root
    signatures_dir = pack_dir / "signatures"
    sig_path = signatures_dir / "publisher.sig"
    pub_path = signatures_dir / "publisher.pubkey"
    if not sig_path.is_file() or not pub_path.is_file():
        return _fail("S5", "missing signatures/publisher.sig or publisher.pubkey")
    signature_bytes = sig_path.read_bytes()
    bundled_pubkey_hex = pub_path.read_bytes().hex()
    # The bundled public key is the same one resolved via the resolver
    # for attestation verification; we trust the resolver, not the
    # pack's own pubkey file, but the two MUST match.
    any_attestation_key_id = next(iter(attestations.values()))["signature"]["key_id"]
    resolved_pubkey_hex = resolver.lookup(manifest.publisher_id, any_attestation_key_id)
    if resolved_pubkey_hex != bundled_pubkey_hex:
        return _fail(
            "S5",
            "signatures/publisher.pubkey does not match the trusted key for this publisher",
        )
    pack_root_hex = _strip_prefix(lock.pack_root)
    if not verify_pack_root(pack_root_hex, signature_bytes, resolved_pubkey_hex):
        return _fail("S5", "publisher signature over pack_root did not verify")

    return VerificationResult(
        ok=True,
        step="S7",
        message="verified",
        content_root=lock.content_root,
        pack_root=lock.pack_root,
        attestations=attestations,
    )
