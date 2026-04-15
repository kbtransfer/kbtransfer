"""Server-side validation for incoming pack submissions (RFC-0002 §4).

The nine checks enumerated in the RFC map 1:1 to `CHECK_NAMES` below.
A successful `validate_submission_bytes` call returns a
`SubmissionValidation` describing everything the caller needs to
commit the tarball into the registry layout; a failure raises
`ValidationError` with a per-check `check` code and an optional
`remediation` hint suitable for the wire response.
"""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Iterable

import json

from kb_pack import PublisherKeyResolver, did_to_safe_path, load_manifest, verify_pack

# Ordered list so success responses can echo checks_passed deterministically.
CHECK_NAMES: tuple[str, ...] = (
    "size_limit",
    "tar_safe_extract",
    "manifest_parse",
    "publisher_admitted",
    "publisher_keys_known",
    "content_root_recompute",
    "signature_verify",
    "attestations_present",
    "residual_risk_notes_nonempty",
    "version_uniqueness",
)


class ValidationError(Exception):
    def __init__(self, check: str, message: str, remediation: str = "") -> None:
        super().__init__(f"[{check}] {message}")
        self.check = check
        self.message = message
        self.remediation = remediation

    def to_wire(self) -> dict[str, str]:
        out = {"check": self.check, "message": self.message}
        if self.remediation:
            out["remediation"] = self.remediation
        return out


@dataclass(frozen=True)
class SubmissionValidation:
    pack_id: str
    version: str
    publisher_id: str
    content_root: str
    pack_root: str
    sha256_hex: str
    size_bytes: int
    tar_bytes: bytes
    extracted_dir_name: str
    checks_passed: list[str] = field(default_factory=list)


def _safe_extract(tar_bytes: bytes, dest: Path) -> Path:
    """Extract to dest; reject path traversal and multi-top-level tars."""
    fileobj = BytesIO(tar_bytes)
    with tarfile.open(fileobj=fileobj, mode="r") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValidationError(
                    "tar_safe_extract",
                    f"tarball entry {name!r} escapes prefix",
                    "rebuild the tarball with kb/publish/0.1 — absolute "
                    "paths and parent refs are rejected",
                )
        fileobj.seek(0)
        with tarfile.open(fileobj=fileobj, mode="r") as tar2:
            try:
                tar2.extractall(dest, filter="data")
            except TypeError:
                tar2.extractall(dest)
    entries = [p for p in dest.iterdir() if p.is_dir()]
    if len(entries) != 1:
        raise ValidationError(
            "tar_safe_extract",
            "tarball did not contain a single top-level directory",
            "rebuild with kb/publish/0.1 which enforces <pack_id>-<version>/ prefix",
        )
    return entries[0]


def _load_resolver(publishers_root: Path) -> PublisherKeyResolver:
    resolver = PublisherKeyResolver()
    if not publishers_root.is_dir():
        return resolver
    for publisher_dir in sorted(publishers_root.iterdir()):
        if not publisher_dir.is_dir():
            continue
        keys_json = publisher_dir / "keys.json"
        if not keys_json.is_file():
            continue
        try:
            doc = json.loads(keys_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        publisher_id = doc.get("publisher_id", "")
        for key in doc.get("keys") or []:
            if key.get("algorithm") != "ed25519":
                continue
            key_id = key.get("key_id")
            hex_val = key.get("public_key_hex")
            if key_id and hex_val and publisher_id:
                resolver.register(publisher_id, key_id, hex_val)
    return resolver


def _map_verify_step_to_check(step: str) -> str:
    if step == "S2":
        return "content_root_recompute"
    if step == "S3a":
        return "attestations_present"
    if step == "S3b":
        return "signature_verify"
    if step == "S3c":
        return "residual_risk_notes_nonempty"
    if step == "S5":
        return "signature_verify"
    return "signature_verify"


def validate_submission_bytes(
    tar_bytes: bytes,
    registry_root: Path,
    *,
    max_bytes: int = 256 * 1024 * 1024,
    trust_role: str = "open",
    allowlist: Iterable[str] | None = None,
) -> SubmissionValidation:
    size_bytes = len(tar_bytes)
    if size_bytes > max_bytes:
        raise ValidationError(
            "size_limit",
            f"submission is {size_bytes} bytes, exceeds {max_bytes}",
            "shrink the pack or ask the operator to raise max_bytes",
        )

    with tempfile.TemporaryDirectory() as staging:
        staging_path = Path(staging)
        try:
            extracted = _safe_extract(tar_bytes, staging_path)
        except tarfile.TarError as exc:
            raise ValidationError(
                "tar_safe_extract",
                f"tarball unreadable: {exc}",
                "submit a valid POSIX tar built by kb/publish/0.1",
            ) from exc

        try:
            manifest = load_manifest(extracted)
        except Exception as exc:
            raise ValidationError(
                "manifest_parse",
                f"pack.manifest.yaml invalid: {exc}",
                "fix manifest and re-run kb/publish/0.1",
            ) from exc

        publisher_id = manifest.publisher_id
        pack_id = manifest.doc["pack_id"]
        version = manifest.doc["version"]

        if trust_role == "consortium":
            allowlist_set = set(allowlist or ())
            if publisher_id not in allowlist_set:
                raise ValidationError(
                    "publisher_admitted",
                    f"publisher {publisher_id!r} not in consortium allowlist",
                    "contact the registry operator to be admitted",
                )

        resolver = _load_resolver(registry_root / "publishers")
        try:
            did_safe = did_to_safe_path(publisher_id)
        except ValueError as exc:
            raise ValidationError(
                "publisher_keys_known",
                f"publisher id {publisher_id!r} is not a valid DID: {exc}",
                "pack manifest publisher.id must be a did:* URI",
            ) from exc
        did_dir = registry_root / "publishers" / did_safe
        if not (did_dir / "keys.json").is_file():
            raise ValidationError(
                "publisher_keys_known",
                f"registry has no keys for publisher {publisher_id!r}",
                "operator must install publishers/<did-safe>/keys.json "
                "before this publisher can submit (Phase 4 limitation; "
                "Phase 5 RFC-0003 will resolve via did:web)",
            )

        result = verify_pack(extracted, resolver)
        if not result.ok:
            check = _map_verify_step_to_check(result.step)
            raise ValidationError(
                check,
                f"verify_pack failed at {result.step}: {result.message}",
                "re-run kb/publish/0.1 with valid attestations and "
                "an active publisher key",
            )

        tar_path_in_registry = (
            registry_root / "packs" / pack_id / f"{version}.tar"
        )
        if tar_path_in_registry.exists():
            raise ValidationError(
                "version_uniqueness",
                f"{pack_id}@{version} already exists in the registry",
                "bump the pack version per semver and re-publish",
            )

        content_root = result.content_root or ""
        pack_root = result.pack_root or ""
        sha256_hex = hashlib.sha256(tar_bytes).hexdigest()

    return SubmissionValidation(
        pack_id=pack_id,
        version=version,
        publisher_id=publisher_id,
        content_root=content_root,
        pack_root=pack_root,
        sha256_hex=sha256_hex,
        size_bytes=size_bytes,
        tar_bytes=tar_bytes,
        extracted_dir_name=f"{pack_id}-{version}",
        checks_passed=list(CHECK_NAMES),
    )
