"""`pack.lock` serialization and parsing.

Format (per spec v0.1.1 §4):

    # pack.lock
    # autoevolve-pack/0.1.1
    # Canonical: sorted by path, LF line endings, no trailing whitespace

    README.md                      sha256:a1b2c3...
    pack.manifest.yaml             sha256:d4e5f6...
    pages/pattern.md               sha256:...

    content_root: sha256:7c4a...e29f
    pack_root:    sha256:3f2a...b91c

Entries are sorted by UTF-8 byte order of their path. Exactly one
blank line separates entries from the two root declarations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kb_pack.merkle import FileEntry, compute_roots

SPEC_HEADER = "autoevolve-pack/0.1.1"


@dataclass(frozen=True)
class Lock:
    entries: list[FileEntry]
    content_root: str
    pack_root: str

    @property
    def content_root_full(self) -> str:
        return f"sha256:{self.content_root}"

    @property
    def pack_root_full(self) -> str:
        return f"sha256:{self.pack_root}"


def build_lock_for(pack_root: Path) -> Lock:
    content_root, packed_root, entries = compute_roots(pack_root)
    return Lock(entries=entries, content_root=content_root, pack_root=packed_root)


def render_lock(lock: Lock) -> str:
    if not lock.entries:
        raise ValueError("Lock has no entries; pack directory is empty.")
    # Column width for the path field: widest path + one space.
    width = max(len(entry.relative_path) for entry in lock.entries) + 1
    lines = [
        "# pack.lock",
        f"# {SPEC_HEADER}",
        "# Canonical: sorted by path, LF line endings, no trailing whitespace",
        "",
    ]
    for entry in lock.entries:
        lines.append(f"{entry.relative_path.ljust(width)}sha256:{entry.sha256_hex}")
    lines.append("")
    lines.append(f"content_root: sha256:{lock.content_root}")
    lines.append(f"pack_root:    sha256:{lock.pack_root}")
    lines.append("")
    return "\n".join(lines)


def write_lock(pack_root: Path, lock: Lock) -> Path:
    target = pack_root / "pack.lock"
    target.write_text(render_lock(lock), encoding="utf-8")
    return target


def parse_lock(text: str) -> Lock:
    entries: list[FileEntry] = []
    content_root = ""
    pack_root = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("content_root:"):
            content_root = line.split(":", 2)[-1].strip()
            continue
        if line.startswith("pack_root:"):
            pack_root = line.split(":", 2)[-1].strip()
            continue
        # Entries look like: path<whitespace>sha256:hex
        if "sha256:" not in line:
            continue
        path_part, hash_part = line.split("sha256:", 1)
        entries.append(FileEntry(path_part.rstrip(), hash_part.strip()))
    if not entries or not content_root or not pack_root:
        raise ValueError("pack.lock is missing required fields")
    return Lock(entries=entries, content_root=content_root, pack_root=pack_root)


def read_lock(pack_root: Path) -> Lock:
    return parse_lock((pack_root / "pack.lock").read_text(encoding="utf-8"))
