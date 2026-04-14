"""Registry client: `file://` + bare-path implementation for Phase 3 v1.

Remote fetch (`https://`, `git+https://`) is specified by the
AutoEvolve registry spec v0.1 §7 but deliberately deferred past
Phase 3 v1. The abstraction is intentionally thin so adding a new
URL scheme later is a single new subclass.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import json

from kb_registry.index import build_index, read_index
from kb_registry.semver import highest_matching


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolveResult:
    pack_id: str
    version: str
    publisher_id: str
    tar_relative_path: str
    sha256: str


class Registry:
    """Read-only registry client.

    Phase 3 v1 only ships the file-backed variant; subclasses can
    replace `_open` / `_fetch_bytes` to add remote transports.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.root = _resolve_registry_root(url)
        if not self.root.is_dir():
            raise RegistryError(f"registry root not found: {self.root}")

    # ── Public API ─────────────────────────────────────────────────
    def describe(self) -> dict[str, Any]:
        index = self._index()
        return {
            "url": self.url,
            "registry_version": index.get("registry_version"),
            "publisher_count": len(index.get("publishers") or {}),
            "pack_count": len(index.get("packs") or {}),
            "updated_at": index.get("updated_at"),
        }

    def list_versions(self, pack_id: str) -> list[str]:
        pack_info = (self._index().get("packs") or {}).get(pack_id)
        if not pack_info:
            return []
        return sorted(v["version"] for v in pack_info.get("versions") or [])

    def resolve(self, pack_id: str, constraint: str = "*") -> ResolveResult:
        pack_info = (self._index().get("packs") or {}).get(pack_id)
        if not pack_info:
            raise RegistryError(f"pack_id {pack_id!r} not found")
        version = highest_matching(
            [v["version"] for v in pack_info["versions"]], constraint
        )
        if version is None:
            raise RegistryError(
                f"no version of {pack_id!r} satisfies {constraint!r}"
            )
        entry = next(v for v in pack_info["versions"] if v["version"] == version)
        return ResolveResult(
            pack_id=pack_id,
            version=version,
            publisher_id=entry.get("publisher_id", ""),
            tar_relative_path=entry["tar"],
            sha256=entry.get("sha256", ""),
        )

    def fetch(self, pack_id: str, version: str, dest: Path) -> Path:
        """Fetch the pack tarball and extract it under `dest`.

        Returns the path to the extracted directory (a single
        top-level directory inside the tarball, as produced by
        `kb/publish/0.1`).
        """
        resolved = self.resolve(pack_id, version)
        tar_path = self.root / resolved.tar_relative_path
        if not tar_path.is_file():
            raise RegistryError(
                f"registry index referenced {resolved.tar_relative_path} "
                "but the file is missing on disk"
            )
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            with tarfile.open(tar_path, "r") as tar:
                try:
                    tar.extractall(staging_path, filter="data")
                except TypeError:
                    tar.extractall(staging_path)
            inner = [p for p in staging_path.iterdir() if p.is_dir()]
            if len(inner) != 1:
                raise RegistryError(
                    "tarball did not contain a single top-level directory"
                )
            target = dest / inner[0].name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(inner[0]), str(target))
            return target

    def publisher_keys(self, publisher_id: str) -> list[dict[str, Any]]:
        publishers = self._index().get("publishers") or {}
        entry = publishers.get(publisher_id)
        if not entry:
            return []
        keys_path = self.root / entry["keys_ref"]
        if not keys_path.is_file():
            return []
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
        return list(doc.get("keys") or [])

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        hits: list[dict[str, Any]] = []
        for pack_id, pack_info in (self._index().get("packs") or {}).items():
            for entry in pack_info.get("versions") or []:
                haystack = " ".join(
                    str(entry.get(field, ""))
                    for field in ("title", "summary", "namespace",
                                  "license_spdx", "publisher_id")
                ).lower()
                if query_lower in pack_id.lower() or query_lower in haystack:
                    hits.append(
                        {
                            "pack_id": pack_id,
                            "version": entry["version"],
                            "title": entry.get("title", ""),
                            "summary": entry.get("summary", ""),
                            "publisher_id": entry.get("publisher_id", ""),
                            "tar": entry.get("tar"),
                        }
                    )
                    if len(hits) >= limit:
                        return hits
        return hits

    def rebuild_index(self) -> Path:
        """Regenerate index.json from the filesystem and return its path."""
        from kb_registry.index import write_index

        return write_index(self.root, build_index(self.root))

    # ── Internals ──────────────────────────────────────────────────
    def _index(self) -> dict[str, Any]:
        return read_index(self.root)


def _resolve_registry_root(url: str) -> Path:
    """Translate a registry URL into a local Path.

    Phase 3 v1 supports only `file://` and bare paths. Anything else
    raises; Phase 3+ can wire real transports by overriding Registry.
    """
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        raw = parsed.path if parsed.scheme == "file" else url
        return Path(unquote(raw)).expanduser().resolve()
    raise RegistryError(
        f"unsupported registry URL scheme: {parsed.scheme!r} "
        "(Phase 3 v1 accepts file:// and bare paths only)"
    )


def open_registry(url: str) -> Registry:
    return Registry(url)
