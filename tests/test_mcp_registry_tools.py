"""Tests for the three new registry MCP tools + registry-mode subscribe."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_registry import write_index


async def _call(root: Path, name: str, args: dict) -> dict:
    result = await HANDLERS[name](root, args)
    return json.loads(result[0].text)


async def _publish_single_pack(
    tmp_path: Path, registry_root: Path, publisher_id: str, pack_id: str, version: str
) -> None:
    kb_root = tmp_path / f"pub-{publisher_id.replace(':','-')}-{pack_id}-{version}"
    scaffold(root=kb_root, tier="individual", publisher_id=publisher_id)
    (kb_root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (kb_root / "wiki" / "patterns" / "p.md").write_text("# Pattern\n", encoding="utf-8")

    await _call(
        kb_root,
        "kb/draft_pack/0.1",
        {
            "pack_id": pack_id,
            "version": version,
            "title": pack_id,
            "summary": "registry tool fixture",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    await _call(kb_root, "kb/distill/0.1", {"pack_id": pack_id})
    pub = await _call(kb_root, "kb/publish/0.1", {"pack_id": pack_id})
    tar_path = kb_root / pub["data"]["tarball"]
    dest = registry_root / "packs" / pack_id / f"{version}.tar"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(tar_path.read_bytes())

    pub_dir = registry_root / "publishers" / publisher_id.replace(":", "-")
    pub_dir.mkdir(parents=True, exist_ok=True)
    key_sidecar = next((kb_root / ".kb" / "keys").glob("*.pub"))
    pub_doc = yaml.safe_load(key_sidecar.read_text())
    (pub_dir / "keys.json").write_text(
        json.dumps(
            {
                "publisher_id": publisher_id,
                "display_name": publisher_id,
                "keys": [
                    {
                        "key_id": pub_doc["key_id"],
                        "algorithm": "ed25519",
                        "public_key_hex": pub_doc["public_key_hex"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
async def registry_and_consumer(tmp_path: Path):
    registry = tmp_path / "reg"
    registry.mkdir()
    await _publish_single_pack(tmp_path, registry, "did:web:pub.example", "demo.reg", "1.0.0")
    await _publish_single_pack(tmp_path, registry, "did:web:pub.example", "demo.reg", "1.2.0")
    write_index(registry)
    consumer = tmp_path / "cons-kb"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")
    return registry, consumer


async def test_registry_describe_reports_counts(registry_and_consumer) -> None:
    registry, consumer = registry_and_consumer
    result = await _call(
        consumer, "kb/registry_describe/0.1", {"registry_url": f"file://{registry}"}
    )
    assert result["ok"] is True
    assert result["data"]["pack_count"] == 1
    assert result["data"]["publisher_count"] == 1


async def test_registry_resolve_returns_highest_caret(registry_and_consumer) -> None:
    registry, consumer = registry_and_consumer
    result = await _call(
        consumer,
        "kb/registry_resolve/0.1",
        {
            "registry_url": f"file://{registry}",
            "pack_id": "demo.reg",
            "constraint": "^1.0",
        },
    )
    assert result["ok"] is True
    assert result["data"]["version"] == "1.2.0"


async def test_registry_resolve_rejects_unsatisfiable(registry_and_consumer) -> None:
    registry, consumer = registry_and_consumer
    result = await _call(
        consumer,
        "kb/registry_resolve/0.1",
        {
            "registry_url": f"file://{registry}",
            "pack_id": "demo.reg",
            "constraint": "^9.0",
        },
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "registry_resolve_failed"


async def test_registry_search_federates_across_urls(tmp_path: Path, registry_and_consumer) -> None:
    registry_a, consumer = registry_and_consumer
    registry_b = tmp_path / "reg-b"
    registry_b.mkdir()
    await _publish_single_pack(tmp_path, registry_b, "did:web:other.example", "other.pack", "0.1.0")
    write_index(registry_b)

    result = await _call(
        consumer,
        "kb/registry_search/0.1",
        {
            "registry_urls": [
                f"file://{registry_a}",
                f"file://{registry_b}",
            ],
            "query": "fixture",
        },
    )
    assert result["ok"] is True
    sources = {hit["registry_url"] for hit in result["data"]["hits"]}
    assert f"file://{registry_a}" in sources
    assert f"file://{registry_b}" in sources


async def test_subscribe_via_registry_url(registry_and_consumer) -> None:
    registry, consumer = registry_and_consumer
    result = await _call(
        consumer,
        "kb/subscribe/0.1",
        {
            "registry_url": f"file://{registry}",
            "pack_id": "demo.reg",
            "constraint": "^1.0",
        },
    )
    assert result["ok"] is True, result
    assert result["data"]["version"] == "1.2.0"
    install_rel = result["data"]["installed_at"]
    assert install_rel.startswith("subscriptions/did-web-pub.example/demo.reg/1.2.0")
    assert (consumer / install_rel / "pack.manifest.yaml").is_file()
