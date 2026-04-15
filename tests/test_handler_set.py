"""Tests for the 2026-04-15 handler-set commit:

- kb/trust_add/0.1
- kb/identity/0.1
- kb/registry_mirror/0.1
- kb/verify_all/0.1
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS


def _call(kb_root: Path, name: str, args: dict) -> dict:
    result = asyncio.run(HANDLERS[name](kb_root, args))
    return json.loads(result[0].text)


def _build_and_subscribe(
    tmp_path: Path,
    *,
    pack_id: str,
    version: str,
    publisher_id: str,
    consumer: Path,
) -> Path:
    pub_kb = tmp_path / f"pub-{pack_id}-{version}"
    scaffold(root=pub_kb, tier="individual", publisher_id=publisher_id)
    (pub_kb / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (pub_kb / "wiki" / "patterns" / "p.md").write_text(
        f"# {pack_id}\n\nBody {version}.\n", encoding="utf-8"
    )
    draft = _call(
        pub_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": pack_id,
            "version": version,
            "title": pack_id,
            "summary": "handler-set fixture.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    assert draft["ok"], draft
    _call(pub_kb, "kb/distill/0.1", {"pack_id": pack_id})
    published = _call(pub_kb, "kb/publish/0.1", {"pack_id": pack_id})
    assert published["ok"], published
    tar_path = pub_kb / published["data"]["tarball"]
    if consumer is not None:
        sub = _call(consumer, "kb/subscribe/0.1", {"source": str(tar_path)})
        assert sub["ok"], sub
    return tar_path


# ── kb/trust_add/0.1 ───────────────────────────────────────────────


@pytest.fixture
def empty_kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    scaffold(root=root, tier="individual", publisher_id="did:web:local.example")
    return root


def test_trust_add_registers_new_publisher(empty_kb: Path) -> None:
    result = _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "display_name": "Friendly",
            "keys": [
                {"key_id": "friend-2026Q2", "public_key_hex": "aa" * 32},
            ],
        },
    )
    assert result["ok"], result
    assert result["data"]["added"] == ["friend-2026Q2"]
    store = yaml.safe_load((empty_kb / ".kb" / "trust-store.yaml").read_text())
    assert "did:web:friend.example" in store["publishers"]


def test_trust_add_rejects_conflicting_key_without_confirm(empty_kb: Path) -> None:
    _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "keys": [{"key_id": "friend-2026Q2", "public_key_hex": "aa" * 32}],
        },
    )
    bad = _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "keys": [{"key_id": "friend-2026Q2", "public_key_hex": "bb" * 32}],
        },
    )
    assert bad["ok"] is False
    assert bad["error"]["code"] == "key_change_detected"
    assert bad["error"]["conflicts"][0]["key_id"] == "friend-2026Q2"


def test_trust_add_replaces_with_confirm(empty_kb: Path) -> None:
    _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "keys": [{"key_id": "friend-2026Q2", "public_key_hex": "aa" * 32}],
        },
    )
    good = _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "keys": [{"key_id": "friend-2026Q2", "public_key_hex": "bb" * 32}],
            "confirm_replace": True,
        },
    )
    assert good["ok"], good
    assert good["data"]["replaced"] == ["friend-2026Q2"]


def test_trust_add_rejects_non_ed25519(empty_kb: Path) -> None:
    bad = _call(
        empty_kb,
        "kb/trust_add/0.1",
        {
            "publisher_id": "did:web:friend.example",
            "keys": [
                {
                    "key_id": "foo",
                    "public_key_hex": "aa" * 32,
                    "algorithm": "secp256k1",
                },
            ],
        },
    )
    assert bad["ok"] is False
    assert bad["error"]["code"] == "unsupported_algorithm"


# ── kb/identity/0.1 ────────────────────────────────────────────────


def test_identity_returns_canonical_whoami(empty_kb: Path) -> None:
    result = _call(empty_kb, "kb/identity/0.1", {})
    assert result["ok"], result
    data = result["data"]
    assert data["publisher_id"] == "did:web:local.example"
    assert data["tier"] == "individual"
    assert data["key_id"]
    assert len(data["public_key_hex"]) == 64


def test_identity_fails_cleanly_on_missing_context(tmp_path: Path) -> None:
    # Empty directory — no .kb/tier.yaml at all.
    result = _call(tmp_path, "kb/identity/0.1", {})
    assert result["ok"] is False
    assert result["error"]["code"] == "publisher_context_missing"


# ── kb/registry_mirror/0.1 ─────────────────────────────────────────


def test_registry_mirror_writes_tarball_and_keys_and_index(
    tmp_path: Path, empty_kb: Path
) -> None:
    # Build a pack locally.
    (empty_kb / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (empty_kb / "wiki" / "patterns" / "p.md").write_text(
        "# mirror fixture\n\nBody.\n", encoding="utf-8"
    )
    draft = _call(
        empty_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": "mirror.pack",
            "version": "1.0.0",
            "title": "Mirror fixture",
            "summary": "mirror.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    assert draft["ok"], draft
    _call(empty_kb, "kb/distill/0.1", {"pack_id": "mirror.pack"})
    published = _call(empty_kb, "kb/publish/0.1", {"pack_id": "mirror.pack"})
    assert published["ok"], published

    registry_root = tmp_path / "mirror-registry"
    registry_root.mkdir()

    result = _call(
        empty_kb,
        "kb/registry_mirror/0.1",
        {
            "pack_id": "mirror.pack",
            "registry_root": str(registry_root),
            "version": "1.0.0",
        },
    )
    assert result["ok"], result
    data = result["data"]
    assert data["mirrored"][0]["version"] == "1.0.0"
    tar_path = registry_root / "packs" / "mirror.pack" / "1.0.0.tar"
    assert tar_path.is_file()
    # Publisher keys written.
    keys_path = next((registry_root / "publishers").rglob("keys.json"))
    keys_doc = json.loads(keys_path.read_text())
    assert keys_doc["publisher_id"] == "did:web:local.example"
    # Index regenerated and lists the pack.
    index = json.loads((registry_root / "index.json").read_text())
    assert "mirror.pack" in index["packs"]


def test_registry_mirror_rejects_missing_tarball(empty_kb: Path, tmp_path: Path) -> None:
    registry_root = tmp_path / "mirror-registry"
    registry_root.mkdir()
    result = _call(
        empty_kb,
        "kb/registry_mirror/0.1",
        {"pack_id": "nonexistent.pack", "registry_root": str(registry_root)},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "no_tarballs_found"


# ── kb/verify_all/0.1 ──────────────────────────────────────────────


def test_verify_all_reports_verified_on_healthy_subscriptions(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")
    _build_and_subscribe(
        tmp_path,
        pack_id="ok.pack",
        version="1.0.0",
        publisher_id="did:web:alice.example",
        consumer=consumer,
    )
    _build_and_subscribe(
        tmp_path,
        pack_id="ok.pack",
        version="1.1.0",
        publisher_id="did:web:alice.example",
        consumer=consumer,
    )

    result = _call(consumer, "kb/verify_all/0.1", {})
    assert result["ok"], result
    data = result["data"]
    assert data["summary"]["total"] == 2
    assert data["summary"]["verified"] == 2
    assert data["summary"]["signature_failed"] == 0
    assert all(row["status"] == "verified" for row in data["subscriptions"])


def test_verify_all_filters_by_publisher(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer-filter"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")
    _build_and_subscribe(
        tmp_path,
        pack_id="a.pack",
        version="1.0.0",
        publisher_id="did:web:alice.example",
        consumer=consumer,
    )
    _build_and_subscribe(
        tmp_path,
        pack_id="b.pack",
        version="1.0.0",
        publisher_id="did:web:bob.example",
        consumer=consumer,
    )

    result = _call(
        consumer,
        "kb/verify_all/0.1",
        {"publisher_id": "did:web:alice.example"},
    )
    assert result["ok"]
    rows = result["data"]["subscriptions"]
    assert len(rows) == 1
    assert rows[0]["publisher_id"] == "did:web:alice.example"


def test_verify_all_returns_empty_when_no_subscriptions(empty_kb: Path) -> None:
    result = _call(empty_kb, "kb/verify_all/0.1", {})
    assert result["ok"]
    assert result["data"]["summary"]["total"] == 0
    assert result["data"]["subscriptions"] == []
