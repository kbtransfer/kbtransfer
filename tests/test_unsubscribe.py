"""Tests for kb/unsubscribe/0.1 — removal of installed subscriptions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS


def _call(root: Path, name: str, args: dict) -> dict:
    result = asyncio.run(HANDLERS[name](root, args))
    return json.loads(result[0].text)


def _publish_and_subscribe(
    tmp_path: Path,
    *,
    pack_id: str,
    version: str,
    publisher_id: str,
    consumer: Path,
) -> Path:
    """Build a pack in a scratch KB, subscribe the consumer to it, return tarball path."""
    pub_kb = tmp_path / f"pub-{pack_id}-{version}"
    scaffold(root=pub_kb, tier="individual", publisher_id=publisher_id)
    (pub_kb / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (pub_kb / "wiki" / "patterns" / "p.md").write_text(
        f"# {pack_id} {version}\n\nBody.\n", encoding="utf-8"
    )

    draft = _call(
        pub_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": pack_id,
            "version": version,
            "title": pack_id,
            "summary": "unsubscribe fixture.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    assert draft["ok"], draft
    _call(pub_kb, "kb/distill/0.1", {"pack_id": pack_id})
    published = _call(pub_kb, "kb/publish/0.1", {"pack_id": pack_id})
    assert published["ok"], published
    tar_path = pub_kb / published["data"]["tarball"]

    sub = _call(
        consumer,
        "kb/subscribe/0.1",
        {"source": str(tar_path)},
    )
    assert sub["ok"], sub
    return tar_path


@pytest.fixture
def consumer_with_two_versions(tmp_path: Path) -> tuple[Path, str]:
    consumer = tmp_path / "consumer-kb"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:consumer.example")
    publisher_id = "did:web:alice.example"
    _publish_and_subscribe(
        tmp_path,
        pack_id="multi.pack",
        version="1.0.0",
        publisher_id=publisher_id,
        consumer=consumer,
    )
    _publish_and_subscribe(
        tmp_path,
        pack_id="multi.pack",
        version="1.1.0",
        publisher_id=publisher_id,
        consumer=consumer,
    )
    return consumer, publisher_id


def _did_safe(did: str) -> str:
    return did.replace(":", "-").replace("/", "-")


def test_unsubscribe_one_version_leaves_the_other(
    consumer_with_two_versions: tuple[Path, str],
) -> None:
    consumer, publisher_id = consumer_with_two_versions
    subs_root = consumer / "subscriptions" / _did_safe(publisher_id) / "multi.pack"
    assert (subs_root / "1.0.0").is_dir()
    assert (subs_root / "1.1.0").is_dir()

    result = _call(
        consumer,
        "kb/unsubscribe/0.1",
        {"publisher_id": publisher_id, "pack_id": "multi.pack", "version": "1.0.0"},
    )
    assert result["ok"], result
    data = result["data"]
    assert data["already_absent"] is False
    assert data["removed"]

    assert not (subs_root / "1.0.0").exists()
    assert (subs_root / "1.1.0").is_dir()


def test_unsubscribe_without_version_removes_all_versions(
    consumer_with_two_versions: tuple[Path, str],
) -> None:
    consumer, publisher_id = consumer_with_two_versions
    subs_root = consumer / "subscriptions" / _did_safe(publisher_id) / "multi.pack"

    result = _call(
        consumer,
        "kb/unsubscribe/0.1",
        {"publisher_id": publisher_id, "pack_id": "multi.pack"},
    )
    assert result["ok"], result
    assert not subs_root.exists()
    # Publisher directory cleaned up since it became empty.
    assert not (consumer / "subscriptions" / _did_safe(publisher_id)).exists()


def test_unsubscribe_idempotent_when_absent(tmp_path: Path) -> None:
    consumer = tmp_path / "empty-consumer"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:consumer.example")
    result = _call(
        consumer,
        "kb/unsubscribe/0.1",
        {"publisher_id": "did:web:ghost.example", "pack_id": "nothing.there"},
    )
    assert result["ok"], result
    assert result["data"]["already_absent"] is True
    assert result["data"]["removed"] == []


def test_unsubscribe_rejects_invalid_publisher_id(tmp_path: Path) -> None:
    consumer = tmp_path / "c"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:consumer.example")
    bad = _call(
        consumer,
        "kb/unsubscribe/0.1",
        {"publisher_id": "not-a-did", "pack_id": "whatever"},
    )
    assert bad["ok"] is False
    assert bad["error"]["code"] == "invalid_publisher_id"


def test_unsubscribe_works_on_read_only_subscription_tree(
    consumer_with_two_versions: tuple[Path, str],
) -> None:
    # Confirm the installed tree really is read-only before unsubscribe.
    consumer, publisher_id = consumer_with_two_versions
    version_dir = consumer / "subscriptions" / _did_safe(publisher_id) / "multi.pack" / "1.0.0"
    manifest = version_dir / "pack.manifest.yaml"
    assert oct(manifest.stat().st_mode & 0o777) == "0o444"

    result = _call(
        consumer,
        "kb/unsubscribe/0.1",
        {"publisher_id": publisher_id, "pack_id": "multi.pack", "version": "1.0.0"},
    )
    assert result["ok"], result
    assert not version_dir.exists()
