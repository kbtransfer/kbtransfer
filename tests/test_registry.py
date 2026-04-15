"""Tests for kb_registry: semver matcher, index build, resolve + fetch."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_registry import (
    HttpsRegistry,
    RegistryError,
    Version,
    build_index,
    highest_matching,
    matches,
    open_registry,
    write_index,
)


def test_version_parses_and_orders() -> None:
    assert Version.parse("1.2.3") == Version(1, 2, 3)
    assert Version.parse("1.2.3") < Version.parse("1.2.4")
    assert Version.parse("2.0.0") > Version.parse("1.99.99")


def test_caret_constraint() -> None:
    assert matches("1.2.3", "^1.2.0")
    assert matches("1.9.9", "^1.0.0")
    assert not matches("2.0.0", "^1.0.0")


def test_tilde_constraint() -> None:
    assert matches("1.2.3", "~1.2.0")
    assert not matches("1.3.0", "~1.2.0")


def test_exact_and_star() -> None:
    assert matches("1.0.0", "=1.0.0")
    assert matches("1.0.0", "1.0.0")
    assert matches("42.0.0", "*")


def test_highest_matching_returns_best_candidate() -> None:
    versions = ["1.0.0", "1.2.3", "1.5.0", "2.0.0"]
    assert highest_matching(versions, "^1.0") == "1.5.0"
    assert highest_matching(versions, "~1.2") == "1.2.3"
    assert highest_matching(versions, ">=1.0") == "2.0.0"
    assert highest_matching(versions, "^3") is None


def _publish_to_registry(
    tmp_path: Path,
    registry_root: Path,
    pack_id: str,
    version: str,
    publisher_id: str,
) -> Path:
    """Build + publish a small pack and drop it into the registry layout."""
    kb_root = tmp_path / f"pub-kb-{pack_id}-{version}"
    scaffold(root=kb_root, tier="individual", publisher_id=publisher_id)
    (kb_root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (kb_root / "wiki" / "patterns" / "p.md").write_text(
        f"# {pack_id}\n\nBody.\n", encoding="utf-8"
    )

    async def run_pipeline() -> Path:
        async def call(name: str, args: dict) -> dict:
            result = await HANDLERS[name](kb_root, args)
            return json.loads(result[0].text)

        draft = await call(
            "kb/draft_pack/0.1",
            {
                "pack_id": pack_id,
                "version": version,
                "title": pack_id,
                "summary": "Registry fixture.",
                "source_pages": ["wiki/patterns/p.md"],
            },
        )
        assert draft["ok"] is True, draft
        await call("kb/distill/0.1", {"pack_id": pack_id})
        pub = await call("kb/publish/0.1", {"pack_id": pack_id})
        assert pub["ok"] is True, pub
        return kb_root / pub["data"]["tarball"]

    tar_path = asyncio.run(run_pipeline())

    # Drop into registry layout.
    dest = registry_root / "packs" / pack_id / f"{version}.tar"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(tar_path.read_bytes())

    # Record the publisher's key.
    pub_dir = registry_root / "publishers" / publisher_id.replace(":", "-")
    pub_dir.mkdir(parents=True, exist_ok=True)
    pub_key_file = next((kb_root / ".kb" / "keys").glob("*.pub"))
    import yaml

    pub_doc = yaml.safe_load(pub_key_file.read_text())
    keys_json = {
        "publisher_id": publisher_id,
        "display_name": "Fixture",
        "keys": [
            {
                "key_id": pub_doc["key_id"],
                "algorithm": "ed25519",
                "public_key_hex": pub_doc["public_key_hex"],
            }
        ],
    }
    keys_file = pub_dir / "keys.json"
    keys_file.write_text(json.dumps(keys_json), encoding="utf-8")
    return tar_path


@pytest.fixture
def registry_with_two_versions(tmp_path: Path) -> Path:
    registry = tmp_path / "reg"
    registry.mkdir()
    _publish_to_registry(tmp_path, registry, "demo.pack", "1.0.0", "did:web:pub.example")
    _publish_to_registry(tmp_path, registry, "demo.pack", "1.2.0", "did:web:pub.example")
    _publish_to_registry(tmp_path, registry, "other.pack", "0.1.0", "did:web:pub.example")
    write_index(registry)
    return registry


def test_build_index_lists_all_versions(registry_with_two_versions: Path) -> None:
    index = build_index(registry_with_two_versions)
    assert index["registry_version"].startswith("kbtransfer-registry/")
    versions = index["packs"]["demo.pack"]["versions"]
    assert sorted(v["version"] for v in versions) == ["1.0.0", "1.2.0"]
    assert "did:web:pub.example" in index["publishers"]


def test_registry_resolve_returns_highest_caret(registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    result = reg.resolve("demo.pack", "^1.0")
    assert result.version == "1.2.0"
    assert result.publisher_id == "did:web:pub.example"
    assert result.tar_relative_path.endswith("1.2.0.tar")


def test_registry_resolve_rejects_unsatisfiable(registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    with pytest.raises(RegistryError):
        reg.resolve("demo.pack", "^5.0")


def test_registry_fetch_extracts_a_usable_pack(tmp_path: Path, registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    dest = tmp_path / "extracted"
    extracted = reg.fetch("demo.pack", "1.0.0", dest)
    assert (extracted / "pack.manifest.yaml").is_file()
    assert (extracted / "pack.lock").is_file()
    assert (extracted / "signatures" / "publisher.sig").is_file()


def test_registry_search_by_pack_id(registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    hits = reg.search("demo")
    assert len(hits) >= 2  # two versions of demo.pack
    assert all(h["pack_id"] == "demo.pack" for h in hits)


def test_registry_publisher_keys_returns_active_keys(registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    keys = reg.publisher_keys("did:web:pub.example")
    assert keys
    assert keys[0]["algorithm"] == "ed25519"
    assert len(keys[0]["public_key_hex"]) == 64


def test_registry_rebuild_index_refreshes_from_disk(registry_with_two_versions: Path) -> None:
    reg = open_registry(f"file://{registry_with_two_versions}")
    # Nuke the index file; it should be rebuilt on demand.
    (registry_with_two_versions / "index.json").unlink()
    path = reg.rebuild_index()
    assert path.is_file()
    assert "demo.pack" in json.loads(path.read_text())["packs"]


# ── HTTPS transport tests ──────────────────────────────────────────
# Real TLS-serving fixtures add setup weight without exercising more
# registry logic than a `_http_get` override already covers. Each test
# builds an HttpsRegistry subclass whose HTTP layer serves bytes from
# a local directory the test controls. The production `_http_get`
# (stdlib urllib.request) is unit-tested implicitly by the empty
# subclass contract — only its stream-read + size-cap + error-map
# behavior lives in `_http_get`, and the rest of the registry logic
# (path safety, sha256 verification, index caching, fetch extraction)
# is in methods exercised below.


class _LocalDirHttpsRegistry(HttpsRegistry):
    """HttpsRegistry variant that serves bytes from a local directory.

    Bypasses real HTTP entirely so the rest of the HTTPS code path
    (sha256 check, path safety, fetch extraction, index caching) can
    be exercised without TLS setup.
    """

    def __init__(self, serve_root: Path, **kwargs: object) -> None:
        super().__init__("https://test.invalid/reg", **kwargs)
        self._serve_root = serve_root

    def _http_get(self, url: str) -> bytes:
        # Strip our fake base prefix and read from disk.
        assert url.startswith(self._base + "/"), url
        rel = url[len(self._base) + 1 :]
        path = self._serve_root / rel
        if not path.is_file():
            raise RegistryError(f"HTTPS fetch failed for {url!r}: 404")
        data = path.read_bytes()
        if len(data) > self._max_bytes:
            raise RegistryError(
                f"response for {url!r} exceeded {self._max_bytes} bytes"
            )
        return data


def test_open_registry_dispatches_https_to_https_subclass() -> None:
    reg = open_registry("https://registry.example.com/kb")
    assert isinstance(reg, HttpsRegistry)


def test_open_registry_accepts_git_plus_https() -> None:
    reg = open_registry("git+https://registry.example.com/kb")
    assert isinstance(reg, HttpsRegistry)


def test_https_registry_rejects_plain_http() -> None:
    with pytest.raises(RegistryError, match="https"):
        HttpsRegistry("http://registry.example.com/kb")


def test_https_registry_rejects_missing_host() -> None:
    with pytest.raises(RegistryError, match="host"):
        HttpsRegistry("https:///kb")


def test_https_registry_describe_resolve_search_roundtrip(
    registry_with_two_versions: Path,
) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions)

    desc = reg.describe()
    assert desc["pack_count"] >= 2
    assert desc["publisher_count"] >= 1

    resolved = reg.resolve("demo.pack", "^1.0")
    assert resolved.version == "1.2.0"
    assert resolved.sha256  # index.py fills sha256 on build
    assert len(resolved.sha256) == 64  # hex

    hits = reg.search("demo")
    assert any(h["pack_id"] == "demo.pack" for h in hits)


def test_https_registry_fetch_extracts_pack_after_sha256_verify(
    tmp_path: Path, registry_with_two_versions: Path
) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    dest = tmp_path / "https-extract"
    extracted = reg.fetch("demo.pack", "1.0.0", dest)
    assert (extracted / "pack.manifest.yaml").is_file()
    assert (extracted / "signatures" / "publisher.sig").is_file()


def test_https_registry_rejects_sha256_mismatch(
    tmp_path: Path, registry_with_two_versions: Path
) -> None:
    # Corrupt the tarball on disk so its sha256 no longer matches the
    # index-declared value. fetch() must refuse before extraction.
    tar_path = next(
        (registry_with_two_versions / "packs" / "demo.pack").glob("1.0.0.tar")
    )
    tampered = tar_path.read_bytes() + b"\x00tamper"
    tar_path.write_bytes(tampered)

    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    with pytest.raises(RegistryError, match="sha256 mismatch"):
        reg.fetch("demo.pack", "1.0.0", tmp_path / "should-not-exist")


def test_https_registry_rejects_path_traversal(
    registry_with_two_versions: Path,
) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    for bad in ["../etc/passwd", "foo/../../bar", "/absolute", "https://evil/x"]:
        with pytest.raises(RegistryError):
            reg._fetch_bytes(bad)


def test_https_registry_refuses_fetch_without_sha256(
    tmp_path: Path, registry_with_two_versions: Path
) -> None:
    # Hand-edit the index to strip sha256 on one version, simulating a
    # registry that did not commit to content hashes.
    index_path = registry_with_two_versions / "index.json"
    index = json.loads(index_path.read_text())
    for v in index["packs"]["demo.pack"]["versions"]:
        v["sha256"] = ""
    index_path.write_text(json.dumps(index))

    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    with pytest.raises(RegistryError, match="no sha256"):
        reg.fetch("demo.pack", "1.0.0", tmp_path / "extract")


def test_https_registry_enforces_size_cap(
    registry_with_two_versions: Path,
) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions, max_bytes=100)
    with pytest.raises(RegistryError, match="exceeded"):
        reg._index()  # index.json is >100 bytes


def test_https_registry_caches_index(registry_with_two_versions: Path) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    reg._index()
    # Delete the on-disk index and confirm the second call uses the cache.
    (registry_with_two_versions / "index.json").unlink()
    assert reg._index()["packs"]  # still returns data


def test_https_registry_rebuild_index_is_disabled() -> None:
    reg = HttpsRegistry("https://registry.example.com/kb")
    with pytest.raises(RegistryError, match="read-only"):
        reg.rebuild_index()


def test_https_registry_publisher_keys_returned_over_fake_wire(
    registry_with_two_versions: Path,
) -> None:
    reg = _LocalDirHttpsRegistry(registry_with_two_versions)
    keys = reg.publisher_keys("did:web:pub.example")
    assert keys
    assert keys[0]["algorithm"] == "ed25519"


def test_subscribe_integration_over_https_registry(
    tmp_path: Path, registry_with_two_versions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end: kb/subscribe/0.1 over an https:// registry URL. We
    # swap kb_registry.open_registry (the function subscribe.py imports
    # at call time) to return our local-dir variant so the integration
    # runs without a real TLS stack but exercises the exact same
    # publish → registry → subscribe → verify path a production
    # consumer would hit.
    import kb_registry

    real_open = kb_registry.open_registry

    def fake_open(url: str):
        if url.startswith("https://"):
            return _LocalDirHttpsRegistry(registry_with_two_versions)
        return real_open(url)

    monkeypatch.setattr(kb_registry, "open_registry", fake_open)

    consumer = tmp_path / "cons-kb"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")

    async def run() -> dict:
        result = await HANDLERS["kb/subscribe/0.1"](
            consumer,
            {
                "registry_url": "https://test.invalid/reg",
                "pack_id": "demo.pack",
                "constraint": "^1.0",
            },
        )
        return json.loads(result[0].text)

    result = asyncio.run(run())
    assert result["ok"] is True, result
    assert result["data"]["version"] == "1.2.0"
    assert result["data"]["installed_at"].startswith(
        "subscriptions/did-web-pub.example/demo.pack/1.2.0"
    )
