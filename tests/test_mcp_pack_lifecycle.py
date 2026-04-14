"""Tests for the Phase 2 MCP tools: draft -> distill -> publish -> subscribe -> verify."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS


def _parse(response) -> dict:
    return json.loads(response[0].text)


async def _call(root: Path, name: str, args: dict) -> dict:
    return _parse(await HANDLERS[name](root, args))


@pytest.fixture
def publisher_kb(tmp_path: Path) -> Path:
    root = tmp_path / "pub-kb"
    scaffold(root=root, tier="individual", publisher_id="did:web:pub.example")
    # Seed a couple of wiki pages so draft_pack has something to copy.
    (root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "patterns" / "replication.md").write_text(
        "# Replication pattern\n\nLag-rate monitoring guidance.\n",
        encoding="utf-8",
    )
    (root / "wiki" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "decisions" / "adr-0001.md").write_text(
        "# ADR 0001\n\nStreaming over logical. Contact alice@example.com.\n",
        encoding="utf-8",
    )
    return root


async def test_draft_pack_creates_skeleton(publisher_kb: Path) -> None:
    result = await _call(
        publisher_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.replication",
            "version": "0.1.0",
            "title": "Streaming replication pattern",
            "summary": "Lag-rate monitoring on top of lag-magnitude alerts.",
            "namespace": "example",
            "source_pages": [
                "wiki/patterns/replication.md",
                "wiki/decisions/adr-0001.md",
            ],
        },
    )
    assert result["ok"] is True, result
    draft = publisher_kb / "drafts" / "example.replication"
    assert (draft / "pack.manifest.yaml").is_file()
    assert (draft / "pages" / "replication.md").is_file()
    assert (draft / "pages" / "adr-0001.md").is_file()
    for kind in ("provenance", "redaction", "evaluation", "license"):
        assert (draft / "attestations" / f"{kind}.json").is_file()


async def test_distill_scrubs_email_and_persists_report(publisher_kb: Path) -> None:
    await _call(
        publisher_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.replication",
            "title": "Streaming replication",
            "summary": "summary",
            "source_pages": ["wiki/decisions/adr-0001.md"],
        },
    )
    result = await _call(publisher_kb, "kb/distill/0.1", {"pack_id": "example.replication"})
    assert result["ok"] is True
    assert result["data"]["mode"] == "manual"
    # The seeded ADR contains alice@example.com; scrubber should have
    # replaced it in place.
    page = (publisher_kb / "drafts" / "example.replication" / "pages" / "adr-0001.md").read_text()
    assert "alice@example.com" not in page
    assert "<EMAIL_01>" in page
    report_path = publisher_kb / "drafts" / "example.replication" / ".distill-report.json"
    assert report_path.is_file()


async def test_publish_emits_tarball_and_signed_draft(publisher_kb: Path) -> None:
    await _call(
        publisher_kb,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.replication",
            "title": "Streaming replication",
            "summary": "summary",
            "source_pages": ["wiki/patterns/replication.md"],
        },
    )
    await _call(publisher_kb, "kb/distill/0.1", {"pack_id": "example.replication"})
    result = await _call(
        publisher_kb,
        "kb/publish/0.1",
        {"pack_id": "example.replication", "composite_score": 0.88},
    )
    assert result["ok"] is True, result
    assert result["data"]["content_root"].startswith("sha256:")
    assert result["data"]["pack_root"].startswith("sha256:")
    tar_rel = result["data"]["tarball"]
    assert tar_rel.startswith("published/")
    assert (publisher_kb / tar_rel).is_file()


async def test_subscribe_verifies_and_installs_pack(tmp_path: Path) -> None:
    publisher = tmp_path / "pub-kb"
    scaffold(root=publisher, tier="individual", publisher_id="did:web:pub.example")
    (publisher / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (publisher / "wiki" / "patterns" / "p.md").write_text(
        "# Pattern\n\nBody.\n", encoding="utf-8"
    )
    await _call(
        publisher,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.p",
            "title": "P",
            "summary": "P.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    await _call(publisher, "kb/distill/0.1", {"pack_id": "example.p"})
    pub_result = await _call(
        publisher, "kb/publish/0.1", {"pack_id": "example.p"}
    )
    tar_path = publisher / pub_result["data"]["tarball"]

    consumer = tmp_path / "cons-kb"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")
    sub_result = await _call(
        consumer, "kb/subscribe/0.1", {"source": str(tar_path)}
    )
    assert sub_result["ok"] is True, sub_result
    install_rel = sub_result["data"]["installed_at"]
    assert install_rel.startswith("subscriptions/did-web-pub.example/example.p/")
    assert (consumer / install_rel / "pack.manifest.yaml").is_file()

    # Trust store should now list the publisher under TOFU.
    ts_text = (consumer / ".kb" / "trust-store.yaml").read_text(encoding="utf-8")
    assert "did:web:pub.example" in ts_text

    verify_result = await _call(
        consumer, "kb/verify/0.1", {"path": install_rel}
    )
    assert verify_result["ok"] is True


async def test_subscribe_enterprise_without_allowlist_rejects(tmp_path: Path) -> None:
    publisher = tmp_path / "pub-kb"
    scaffold(root=publisher, tier="individual", publisher_id="did:web:rogue.example")
    (publisher / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (publisher / "wiki" / "patterns" / "p.md").write_text("# P\n", encoding="utf-8")
    await _call(
        publisher,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.p",
            "title": "P",
            "summary": "P.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    await _call(publisher, "kb/distill/0.1", {"pack_id": "example.p"})
    pub_result = await _call(publisher, "kb/publish/0.1", {"pack_id": "example.p"})
    tar_path = publisher / pub_result["data"]["tarball"]

    consumer = tmp_path / "cons-kb"
    scaffold(root=consumer, tier="enterprise", publisher_id="did:web:cons.example")

    sub_result = await _call(
        consumer, "kb/subscribe/0.1", {"source": str(tar_path)}
    )
    assert sub_result["ok"] is False
    assert sub_result["error"]["code"] == "untrusted_publisher"


async def test_search_across_mine_and_subscriptions(tmp_path: Path) -> None:
    publisher = tmp_path / "pub-kb"
    scaffold(root=publisher, tier="individual", publisher_id="did:web:pub.example")
    (publisher / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (publisher / "wiki" / "patterns" / "page.md").write_text(
        "# Pattern\n\nuniqueword-alpha in the published content.\n", encoding="utf-8"
    )
    await _call(
        publisher,
        "kb/draft_pack/0.1",
        {
            "pack_id": "example.alpha",
            "title": "Alpha",
            "summary": "Alpha",
            "source_pages": ["wiki/patterns/page.md"],
        },
    )
    await _call(publisher, "kb/distill/0.1", {"pack_id": "example.alpha"})
    pub_result = await _call(publisher, "kb/publish/0.1", {"pack_id": "example.alpha"})
    tar_path = publisher / pub_result["data"]["tarball"]

    consumer = tmp_path / "cons-kb"
    scaffold(root=consumer, tier="individual", publisher_id="did:web:cons.example")
    (consumer / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (consumer / "wiki" / "patterns" / "own.md").write_text(
        "# Mine\n\nuniqueword-alpha also appears locally.\n", encoding="utf-8"
    )
    await _call(consumer, "kb/subscribe/0.1", {"source": str(tar_path)})

    search = await _call(consumer, "kb/search/0.1", {"query": "uniqueword-alpha"})
    sources = {hit["source"] for hit in search["data"]["hits"]}
    assert "mine" in sources
    assert any(s.startswith("from:did-web-pub.example") for s in sources)
