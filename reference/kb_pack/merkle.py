"""Two-merkle-root computation per spec v0.1.1 §4 (amendment A1).

Splitting the pack's integrity root into two roots breaks the
circular dependency between attestations and the content they
attest to:

    content_root = sha256 over { README.md, pack.manifest.yaml, pages/** }
    pack_root    = sha256 over content_files + { attestations/** }

Attestations embed `content_root` as an explicit field (A1), so a
stolen publisher key cannot reuse a legitimate older attestation on
new malicious content. The publisher signature covers `pack_root`.

File inclusion rule per amendment B3: every file under the pack
root, recursively, is considered EXCEPT `pack.lock` itself and
anything under `signatures/`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

EXCLUDED_TOP_LEVEL = {"pack.lock"}
EXCLUDED_DIRS = {"signatures"}
CONTENT_PREFIXES = ("README.md", "pack.manifest.yaml", "pages/")


@dataclass(frozen=True)
class FileEntry:
    relative_path: str
    sha256_hex: str


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _iter_pack_files(pack_root: Path) -> list[Path]:
    result: list[Path] = []
    for path in sorted(pack_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(pack_root)
        parts = relative.parts
        if parts[0] in EXCLUDED_DIRS:
            continue
        if len(parts) == 1 and parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        result.append(path)
    return result


def collect_pack_entries(pack_root: Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    for path in _iter_pack_files(pack_root):
        rel = "/".join(path.relative_to(pack_root).parts)
        entries.append(FileEntry(rel, _sha256_file(path)))
    entries.sort(key=lambda e: e.relative_path.encode("utf-8"))
    return entries


def _merkle_of(entries: list[FileEntry]) -> str:
    sorted_entries = sorted(entries, key=lambda e: e.relative_path.encode("utf-8"))
    canonical = "".join(
        f"{entry.relative_path}:{entry.sha256_hex}\n" for entry in sorted_entries
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_content_file(relative_path: str) -> bool:
    return any(relative_path == prefix or relative_path.startswith(prefix)
               for prefix in CONTENT_PREFIXES)


def compute_roots(pack_root: Path) -> tuple[str, str, list[FileEntry]]:
    """Compute (content_root, pack_root, entries) for a pack directory."""
    entries = collect_pack_entries(pack_root)
    content_entries = [e for e in entries if _is_content_file(e.relative_path)]
    content_root = _merkle_of(content_entries)
    packed_root = _merkle_of(entries)
    return content_root, packed_root, entries
