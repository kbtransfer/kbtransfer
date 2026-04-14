"""Pack build + verify per AutoEvolve pack spec v0.1.1.

Public surface:
    canonical_json           — canonical-2026-04 JSON encoder
    Manifest, load_manifest  — manifest loading + validation
    compute_roots            — two-merkle computation
    Lock, build_lock_for, write_lock, read_lock, render_lock, parse_lock
"""

from __future__ import annotations

__version__ = "0.1.0"

from kb_pack.attestation import (
    KINDS as ATTESTATION_KINDS,
    AttestationError,
    build_envelope,
    build_evaluation,
    build_license,
    build_provenance,
    build_redaction,
    load_attestation,
    write_attestation,
)
from kb_pack.build import BuildError, BuildResult, build_pack
from kb_pack.canonical import canonical_json
from kb_pack.lock import (
    Lock,
    build_lock_for,
    parse_lock,
    read_lock,
    render_lock,
    write_lock,
)
from kb_pack.manifest import (
    REQUIRED_ATTESTATIONS,
    REQUIRED_FIELDS,
    SPEC_VERSION,
    Manifest,
    ManifestError,
    load_manifest,
    validate,
)
from kb_pack.merkle import FileEntry, collect_pack_entries, compute_roots
from kb_pack.signature import (
    ALGORITHM,
    make_envelope,
    sign_attestation,
    sign_pack_root,
    validate_envelope,
    verify_attestation_signature,
    verify_pack_root,
)
from kb_pack.dependency import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_INHERIT_DEPTH,
    RecursiveVerificationResult,
    verify_with_dependencies,
)
from kb_pack.verify import PublisherKeyResolver, VerificationResult, verify_pack

__all__ = [
    "ALGORITHM",
    "ATTESTATION_KINDS",
    "AttestationError",
    "BuildError",
    "BuildResult",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_INHERIT_DEPTH",
    "RecursiveVerificationResult",
    "verify_with_dependencies",
    "FileEntry",
    "Lock",
    "Manifest",
    "ManifestError",
    "PublisherKeyResolver",
    "REQUIRED_ATTESTATIONS",
    "REQUIRED_FIELDS",
    "SPEC_VERSION",
    "VerificationResult",
    "build_envelope",
    "build_evaluation",
    "build_license",
    "build_lock_for",
    "build_pack",
    "build_provenance",
    "build_redaction",
    "canonical_json",
    "collect_pack_entries",
    "compute_roots",
    "load_attestation",
    "load_manifest",
    "make_envelope",
    "parse_lock",
    "read_lock",
    "render_lock",
    "sign_attestation",
    "sign_pack_root",
    "validate",
    "validate_envelope",
    "verify_attestation_signature",
    "verify_pack",
    "verify_pack_root",
    "write_attestation",
    "write_lock",
]
