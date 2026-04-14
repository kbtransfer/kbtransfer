"""Direct handler tests for the Phase 1 MCP tools.

These tests exercise each tool's HANDLER coroutine against a real KB
produced by `kb init`, without going through the stdio transport.
Transport-level smoke tests live in `test_mcp_server.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS, TOOLS


def _parse(response) -> dict:
    assert len(response) == 1
    return json.loads(response[0].text)


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    scaffold(root=root, tier="individual", publisher_id="did:web:test.example")
    return root


def test_all_phase1_tools_registered() -> None:
    names = {t.name for t in TOOLS}
    expected = {
        "kb/search/0.1",
        "kb/read/0.1",
        "kb/write/0.1",
        "kb/ingest_source/0.1",
        "kb/lint/0.1",
        "kb/policy_get/0.1",
        "kb/policy_set/0.1",
    }
    assert names == expected


async def test_policy_get_returns_tier_policy(kb: Path) -> None:
    result = _parse(await HANDLERS["kb/policy_get/0.1"](kb, {}))
    assert result["ok"] is True
    assert result["data"]["policy"]["tier"] == "individual"


async def test_policy_set_updates_nested_key(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/policy_set/0.1"](
            kb,
            {"key": "consumer.redaction_level_min", "value": "standard"},
        )
    )
    assert result["ok"] is True
    assert result["data"]["policy"]["consumer"]["redaction_level_min"] == "standard"
    reloaded = yaml.safe_load((kb / ".kb" / "policy.yaml").read_text())
    assert reloaded["consumer"]["redaction_level_min"] == "standard"


async def test_policy_set_creates_missing_intermediates(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/policy_set/0.1"](
            kb,
            {"key": "experimental.new_flag", "value": True},
        )
    )
    assert result["ok"] is True
    assert result["data"]["policy"]["experimental"]["new_flag"] is True


async def test_read_rejects_escape_outside_kb(kb: Path) -> None:
    result = _parse(await HANDLERS["kb/read/0.1"](kb, {"path": "../etc/passwd"}))
    assert result["ok"] is False
    assert result["error"]["code"] == "forbidden_path"


async def test_read_rejects_kb_config_read(kb: Path) -> None:
    result = _parse(await HANDLERS["kb/read/0.1"](kb, {"path": ".kb/policy.yaml"}))
    assert result["ok"] is False
    assert result["error"]["code"] == "forbidden_path"


async def test_read_returns_wiki_index(kb: Path) -> None:
    result = _parse(await HANDLERS["kb/read/0.1"](kb, {"path": "wiki/index.md"}))
    assert result["ok"] is True
    assert "Wiki Index" in result["data"]["content"]


async def test_write_creates_new_page_and_logs(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/write/0.1"](
            kb,
            {"path": "wiki/patterns/sample.md", "content": "# Sample\n\nHi."},
        )
    )
    assert result["ok"] is True
    page = kb / "wiki" / "patterns" / "sample.md"
    assert page.is_file()
    assert "Sample" in page.read_text()
    assert "wrote wiki/patterns/sample.md" in (kb / "wiki" / "log.md").read_text()


async def test_write_rejects_subscription_paths(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/write/0.1"](
            kb,
            {"path": "subscriptions/whoever/pack/page.md", "content": "nope"},
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "forbidden_path"


async def test_search_tags_own_wiki_as_mine(kb: Path) -> None:
    await HANDLERS["kb/write/0.1"](
        kb,
        {"path": "wiki/decisions/adr-0001.md", "content": "# ADR 0001\n\nchose Postgres."},
    )
    result = _parse(await HANDLERS["kb/search/0.1"](kb, {"query": "postgres"}))
    assert result["ok"] is True
    assert result["data"]["count"] >= 1
    assert all(hit["source"] == "mine" for hit in result["data"]["hits"])


async def test_search_scope_subscriptions_is_empty_when_none(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/search/0.1"](
            kb, {"query": "anything", "scope": "subscriptions"}
        )
    )
    assert result["ok"] is True
    assert result["data"]["count"] == 0


async def test_search_tags_subscription_hits_with_publisher(kb: Path) -> None:
    sub_page = kb / "subscriptions" / "did-web-acme" / "pattern-x" / "1.0.0" / "pages" / "pattern.md"
    sub_page.parent.mkdir(parents=True, exist_ok=True)
    sub_page.write_text("# Imported\n\nunique-subscription-marker", encoding="utf-8")
    result = _parse(
        await HANDLERS["kb/search/0.1"](kb, {"query": "unique-subscription-marker"})
    )
    assert result["ok"] is True
    assert result["data"]["count"] >= 1
    hit = result["data"]["hits"][0]
    assert hit["source"].startswith("from:did-web-acme")


async def test_lint_passes_on_fresh_kb(kb: Path) -> None:
    result = _parse(await HANDLERS["kb/lint/0.1"](kb, {}))
    assert result["ok"] is True
    assert result["data"]["counts"]["error"] == 0


async def test_lint_flags_missing_required_folder(kb: Path) -> None:
    import shutil

    shutil.rmtree(kb / "wiki" / "decisions")
    result = _parse(await HANDLERS["kb/lint/0.1"](kb, {}))
    assert result["ok"] is True
    assert result["data"]["counts"]["error"] >= 1
    assert any(
        f["rule"] == "required_folder_missing" and "decisions" in f["path"]
        for f in result["data"]["findings"]
    )


async def test_ingest_source_saves_source_and_returns_plan(kb: Path) -> None:
    result = _parse(
        await HANDLERS["kb/ingest_source/0.1"](
            kb,
            {
                "title": "Postgres HA setup",
                "content": (
                    "We evaluated Postgres replication options. Streaming replication "
                    "with a hot standby was chosen over logical replication because "
                    "we needed read scaling."
                ),
                "origin": "confluence://ops/postgres-ha",
            },
        )
    )
    assert result["ok"] is True
    assert result["data"]["source_path"].startswith("sources/")
    saved = kb / result["data"]["source_path"]
    assert saved.is_file()
    assert "confluence://ops/postgres-ha" in saved.read_text()
    assert "patterns" in result["data"]["suggested_folders"]
    assert "postgres" in result["data"]["keywords"]


async def test_unknown_tool_name_returns_envelope_error(kb: Path) -> None:
    # The registry itself does not expose unknown tools; this just confirms
    # the envelope stays well-formed when a caller invents a bad key.
    from kb_mcp_server.envelope import error

    response = error("unknown_tool", "No tool named kb/bogus/0.1")
    parsed = json.loads(response[0].text)
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "unknown_tool"
