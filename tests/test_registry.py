"""Tests for kb_registry: semver matcher, index build, resolve + fetch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_registry import (
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
