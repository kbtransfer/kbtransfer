"""Pack build + verify per AutoEvolve pack spec v0.1.1.

Public surface:
    canonical_json           — canonical-2026-04 JSON encoder
    Manifest, load_manifest  — manifest loading + validation
    compute_roots            — two-merkle computation
    Lock, build_lock_for, write_lock, read_lock, render_lock, parse_lock
"""

from __future__ import annotations

__version__ = "0.1.0"

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

__all__ = [
    "FileEntry",
    "Lock",
    "Manifest",
    "ManifestError",
    "REQUIRED_ATTESTATIONS",
    "REQUIRED_FIELDS",
    "SPEC_VERSION",
    "build_lock_for",
    "canonical_json",
    "collect_pack_entries",
    "compute_roots",
    "load_manifest",
    "parse_lock",
    "read_lock",
    "render_lock",
    "validate",
    "write_lock",
]
