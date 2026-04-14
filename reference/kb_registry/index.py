"""index.json shape + rebuild logic for a kb-registry.

The registry's ground truth is the filesystem layout:

    registry-root/
      publishers/<did-dir>/keys.json
      packs/<pack_id>/<version>.tar

index.json is a denormalized cache that every consumer reads first
for fast discovery. `rebuild_index` regenerates it from the
filesystem so a CI job (or a registry operator) can always produce
the authoritative shape without manual editing.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

INDEX_VERSION = "kbtransfer-registry/0.1"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_manifest(tar_path: Path) -> dict[str, Any] | None:
    try:
        with tarfile.open(tar_path, "r") as tar:
            for member in tar.getmembers():
                if member.name.endswith("/pack.manifest.yaml") and not member.isdir():
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    return yaml.safe_load(extracted.read().decode("utf-8"))
    except (tarfile.TarError, OSError, yaml.YAMLError):
        return None
    return None


def _did_dir_name(publisher_id: str) -> str:
    return publisher_id.replace(":", "-").replace("/", "-")


def _load_publishers(registry_root: Path) -> dict[str, Any]:
    publishers_root = registry_root / "publishers"
    publishers: dict[str, Any] = {}
    if not publishers_root.is_dir():
        return publishers
    for publisher_dir in sorted(publishers_root.iterdir()):
        if not publisher_dir.is_dir():
            continue
        keys_file = publisher_dir / "keys.json"
        if not keys_file.is_file():
            continue
        try:
            doc = json.loads(keys_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        publisher_id = doc.get("publisher_id")
        if not publisher_id:
            continue
        publishers[publisher_id] = {
            "display_name": doc.get("display_name", ""),
            "keys_ref": str(keys_file.relative_to(registry_root)),
            "key_count": len(doc.get("keys") or []),
        }
    return publishers


def _load_packs(registry_root: Path) -> dict[str, Any]:
    packs_root = registry_root / "packs"
    packs: dict[str, Any] = {}
    if not packs_root.is_dir():
        return packs
    for pack_dir in sorted(packs_root.iterdir()):
        if not pack_dir.is_dir():
            continue
        versions: list[dict[str, Any]] = []
        for tar_path in sorted(pack_dir.glob("*.tar")):
            version = tar_path.stem
            manifest = _extract_manifest(tar_path) or {}
            versions.append(
                {
                    "version": version,
                    "tar": str(tar_path.relative_to(registry_root)),
                    "size_bytes": tar_path.stat().st_size,
                    "sha256": _sha256_file(tar_path),
                    "publisher_id": (manifest.get("publisher") or {}).get("id", ""),
                    "title": manifest.get("title", ""),
                    "summary": manifest.get("summary", ""),
                    "namespace": manifest.get("namespace", ""),
                    "license_spdx": (manifest.get("license") or {}).get("spdx", ""),
                }
            )
        if versions:
            packs[pack_dir.name] = {"versions": versions}
    return packs


def build_index(registry_root: Path) -> dict[str, Any]:
    return {
        "registry_version": INDEX_VERSION,
        "updated_at": _now(),
        "publishers": _load_publishers(registry_root),
        "packs": _load_packs(registry_root),
    }


def write_index(registry_root: Path, index: dict[str, Any] | None = None) -> Path:
    if index is None:
        index = build_index(registry_root)
    target = registry_root / "index.json"
    target.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return target


def read_index(registry_root: Path) -> dict[str, Any]:
    path = registry_root / "index.json"
    if not path.is_file():
        return build_index(registry_root)
    return json.loads(path.read_text(encoding="utf-8"))
