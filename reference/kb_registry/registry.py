"""Registry client: file + HTTPS transports.

`file://` and bare-path URLs go through the filesystem-backed
`Registry`. `https://` and `git+https://` go through `HttpsRegistry`,
which fetches index.json and tarballs over TLS with sha256
verification against the index-declared hash. Consumers use
`open_registry(url)` — it dispatches by scheme.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse

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
    """Translate a local registry URL into a Path.

    This is only called for filesystem-backed registries; HTTPS URLs
    bypass it via `HttpsRegistry`.
    """
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        raw = parsed.path if parsed.scheme == "file" else url
        return Path(unquote(raw)).expanduser().resolve()
    raise RegistryError(
        f"filesystem registry expected file:// or bare path, got {parsed.scheme!r}"
    )


_HTTPS_MAX_BYTES_DEFAULT = 256 * 1024 * 1024  # 256 MB hard cap per response
_HTTPS_TIMEOUT_DEFAULT = 30.0  # seconds


class HttpsRegistry(Registry):
    """Read-only HTTPS-backed registry client.

    Fetches `index.json` over TLS, then downloads tarballs per pack
    and verifies each against the index-declared sha256 BEFORE the
    tarball is opened. This is the minimum bar for trusting a remote
    registry — an on-path attacker who can break TLS still cannot
    substitute pack content the index commits to.

    Defense in depth: packs are separately Ed25519-signed by their
    publisher; even a fully-compromised registry that forges both
    index.json and a matching tarball will fail `verify_pack` at the
    consumer (the publisher key comes from the consumer's trust store,
    not the registry). HTTPS is the delivery integrity layer; the
    pack signature is the authorship layer.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = _HTTPS_TIMEOUT_DEFAULT,
        max_bytes: int = _HTTPS_MAX_BYTES_DEFAULT,
    ) -> None:
        parsed = urlparse(url)
        scheme = parsed.scheme
        if scheme == "git+https":
            scheme = "https"
        if scheme != "https":
            raise RegistryError(
                f"HttpsRegistry requires https:// or git+https://, got {url!r}"
            )
        if not parsed.netloc:
            raise RegistryError(f"HTTPS registry URL missing host: {url!r}")
        # Base URL = https://<netloc><path> with trailing slash trimmed; all
        # relative fetches join against this base.
        self.url = url
        self._base = f"https://{parsed.netloc}{parsed.path.rstrip('/')}"
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._index_cache: dict[str, Any] | None = None

    # ── HTTP layer (overridable for tests) ─────────────────────────
    def _http_get(self, url: str) -> bytes:
        request = urllib.request.Request(
            url, headers={"User-Agent": "kbtransfer/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                total = 0
                chunks: list[bytes] = []
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._max_bytes:
                        raise RegistryError(
                            f"response for {url!r} exceeded {self._max_bytes} bytes"
                        )
                    chunks.append(chunk)
        except (URLError, HTTPError) as exc:
            raise RegistryError(f"HTTPS fetch failed for {url!r}: {exc}") from exc
        return b"".join(chunks)

    def _fetch_bytes(
        self, rel_path: str, *, expected_sha256: str | None = None
    ) -> bytes:
        # Reject absolute URLs, traversal, and empty paths — rel_path is
        # always relative to the registry base; anything else is malformed
        # index.json content and we refuse to fetch it.
        if not rel_path or "://" in rel_path or rel_path.startswith("/"):
            raise RegistryError(f"unsafe registry path: {rel_path!r}")
        if rel_path.startswith("..") or "/.." in rel_path:
            raise RegistryError(f"path traversal rejected: {rel_path!r}")
        url = f"{self._base}/{rel_path}"
        data = self._http_get(url)
        if expected_sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                raise RegistryError(
                    f"sha256 mismatch for {url!r}: "
                    f"expected {expected_sha256}, got {actual}"
                )
        return data

    # ── Overrides that replace local-filesystem reads ──────────────
    def _index(self) -> dict[str, Any]:
        if self._index_cache is None:
            raw = self._fetch_bytes("index.json")
            self._index_cache = json.loads(raw.decode("utf-8"))
        return self._index_cache

    def fetch(self, pack_id: str, version: str, dest: Path) -> Path:
        resolved = self.resolve(pack_id, version)
        if not resolved.sha256:
            raise RegistryError(
                f"index entry for {pack_id} {version} has no sha256; "
                "refusing to fetch unverified content over HTTPS"
            )
        tarball_bytes = self._fetch_bytes(
            resolved.tar_relative_path, expected_sha256=resolved.sha256
        )
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            tar_tmp = staging_path / "pack.tar"
            tar_tmp.write_bytes(tarball_bytes)
            extracted = staging_path / "extracted"
            extracted.mkdir()
            with tarfile.open(tar_tmp, "r") as tar:
                try:
                    tar.extractall(extracted, filter="data")
                except TypeError:
                    tar.extractall(extracted)
            inner = [p for p in extracted.iterdir() if p.is_dir()]
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
        entry = (self._index().get("publishers") or {}).get(publisher_id)
        if not entry:
            return []
        raw = self._fetch_bytes(entry["keys_ref"])
        doc = json.loads(raw.decode("utf-8"))
        return list(doc.get("keys") or [])

    def rebuild_index(self) -> Path:
        raise RegistryError(
            "HTTPS registries are read-only; rebuild at the source and redeploy"
        )

    # ── RFC-0002: submit path ──────────────────────────────────────
    def submit(
        self,
        tarball_path: Path,
        *,
        notes: str = "",
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        tarball_path = Path(tarball_path)
        if not tarball_path.is_file():
            raise RegistryError(f"tarball not found: {tarball_path}")
        if tarball_path.stat().st_size > self._max_bytes:
            raise RegistryError(
                f"tarball exceeds client max_bytes cap {self._max_bytes}"
            )
        body = tarball_path.read_bytes()
        response = self._http_submit(
            f"{self._base}/v0.1/submit",
            tar_bytes=body,
            filename=tarball_path.name,
            notes=notes,
            bearer_token=bearer_token,
        )
        # Invalidate the cached index so a follow-up resolve sees the new
        # version (assuming the registry committed it in auto mode).
        self._index_cache = None
        return response

    def _http_submit(
        self,
        url: str,
        *,
        tar_bytes: bytes,
        filename: str,
        notes: str,
        bearer_token: str | None,
    ) -> dict[str, Any]:
        boundary = f"----kbtransfer-{uuid.uuid4().hex}"
        body = _build_multipart(
            boundary=boundary,
            tar_bytes=tar_bytes,
            filename=filename,
            notes=notes,
        )
        headers = {
            "User-Agent": "kbtransfer/0.1",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read()
                status = resp.status
        except HTTPError as exc:
            # Even on 4xx we still want the structured error body back.
            raw = exc.read() if hasattr(exc, "read") else b""
            status = exc.code
        except URLError as exc:
            raise RegistryError(f"submit HTTPS POST failed: {exc}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError as exc:
            raise RegistryError(
                f"registry returned non-JSON response (HTTP {status}): {raw[:200]!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise RegistryError(
                f"registry submit response was not a JSON object: {parsed!r}"
            )
        return parsed


def _build_multipart(
    *,
    boundary: str,
    tar_bytes: bytes,
    filename: str,
    notes: str,
) -> bytes:
    crlf = b"\r\n"
    parts: list[bytes] = []
    if notes:
        parts.append(f"--{boundary}".encode())
        parts.append(b'Content-Disposition: form-data; name="notes"')
        parts.append(b"")
        parts.append(notes.encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="tarball"; filename="{filename}"'.encode()
    )
    parts.append(b"Content-Type: application/x-tar")
    parts.append(b"")
    header = crlf.join(parts) + crlf
    trailer = crlf + f"--{boundary}--".encode() + crlf
    return header + tar_bytes + trailer


def open_registry(url: str) -> Registry:
    parsed = urlparse(url)
    if parsed.scheme in ("https", "git+https"):
        return HttpsRegistry(url)
    return Registry(url)
