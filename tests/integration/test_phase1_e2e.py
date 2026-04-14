"""End-to-end Phase 1 dogfood.

Scripts a realistic agent-style flow against a freshly scaffolded KB:

1. `kb init` creates the KB skeleton.
2. Agent ingests a source via `kb/ingest_source/0.1`, receives a plan.
3. Agent reads the saved source back via `kb/read/0.1`.
4. Agent composes a pattern page, a decision page, and a
   failure-log page via `kb/write/0.1`, appending to wiki/log.md
   transparently.
5. Agent queries `kb/search/0.1` and confirms every hit is tagged
   `mine` (no subscriptions yet).
6. A fake subscription is planted under `subscriptions/` to prove
   cross-source search tagging works end-to-end.
7. `kb/lint/0.1` reports zero errors and the expected orphan warnings.
8. `kb/policy_get/0.1` + `kb/policy_set/0.1` prove the policy round-trip.

This test is the tiebreaker: if it passes, Phase 1 is functionally
complete for one-user single-KB scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS


def _parse(response) -> dict:
    return json.loads(response[0].text)


async def _call(root: Path, name: str, args: dict) -> dict:
    return _parse(await HANDLERS[name](root, args))


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "dogfood-kb"
    scaffold(root=root, tier="team", publisher_id="did:web:team.example")
    return root


async def test_phase1_end_to_end_flow(kb: Path) -> None:
    # ── Step 1: ingest a source ───────────────────────────────────────
    source_text = (
        "We rolled out Postgres streaming replication for the billing cluster. "
        "Two weeks in, a network partition caused the standby to fall behind "
        "by 47 seconds before the monitor noticed. We had chosen streaming "
        "over logical replication because we needed row-level consistency, "
        "but the monitor threshold was tuned for bursty load, not a slow "
        "silent drift. Fix: added a lag-rate alert on top of lag-magnitude."
    )
    ingest = await _call(
        kb,
        "kb/ingest_source/0.1",
        {
            "title": "Postgres replication lag incident",
            "content": source_text,
            "origin": "pagerduty://incident/42",
        },
    )
    assert ingest["ok"] is True
    source_path = ingest["data"]["source_path"]
    assert source_path.startswith("sources/")
    assert "replication" in ingest["data"]["keywords"]

    # ── Step 2: read the saved source back ────────────────────────────
    readback = await _call(kb, "kb/read/0.1", {"path": source_path})
    assert readback["ok"] is True
    assert "streaming replication" in readback["data"]["content"]
    assert "pagerduty://incident/42" in readback["data"]["content"]

    # ── Step 3: compose the three first-class experience pages ───────
    pattern_page = (
        "# Pattern: Streaming Replication with Lag-Rate Alert\n\n"
        "## Problem\nDetect silent standby drift before it breaks failover SLAs.\n\n"
        "## Solution\nMonitor both lag magnitude AND lag rate-of-change. "
        "Bursty-tuned thresholds miss slow drifts.\n\n"
        "See [`wiki/decisions/adr-0003-streaming-over-logical.md`](../decisions/adr-0003-streaming-over-logical.md)."
    )
    decision_page = (
        "# ADR-0003: Streaming over logical replication for billing\n\n"
        "## Decision\nStreaming replication chosen for the billing cluster.\n\n"
        "## Context\nRow-level consistency required; logical replication would "
        "have weakened guarantees under our workload.\n\n"
        "## Consequences\nStandby failover possible but requires lag-rate "
        "monitoring — see [`wiki/failure-log/2026-03-27-replication-drift.md`](../failure-log/2026-03-27-replication-drift.md)."
    )
    failure_page = (
        "# 2026-03-27 — Silent replication drift on billing standby\n\n"
        "## What broke\nStandby fell 47 seconds behind; failover would "
        "have lost transactions.\n\n"
        "## Root cause\nMonitor threshold tuned for bursty load missed "
        "slow silent drift.\n\n"
        "## Fix\nAdded a lag-rate alert alongside existing lag-magnitude "
        "alert. See [`wiki/patterns/streaming-replication-lag-rate.md`](../patterns/streaming-replication-lag-rate.md)."
    )
    for path, body in [
        ("wiki/patterns/streaming-replication-lag-rate.md", pattern_page),
        ("wiki/decisions/adr-0003-streaming-over-logical.md", decision_page),
        ("wiki/failure-log/2026-03-27-replication-drift.md", failure_page),
    ]:
        write = await _call(kb, "kb/write/0.1", {"path": path, "content": body})
        assert write["ok"] is True, write

    log_text = (kb / "wiki" / "log.md").read_text()
    assert log_text.count("wrote wiki/") == 3

    # ── Step 4: search confirms every own-wiki hit is tagged mine ────
    search_mine = await _call(kb, "kb/search/0.1", {"query": "replication"})
    assert search_mine["ok"] is True
    assert search_mine["data"]["count"] >= 3
    assert all(hit["source"] == "mine" for hit in search_mine["data"]["hits"])

    # ── Step 5: plant a subscription and re-search to verify tagging ─
    sub_dir = kb / "subscriptions" / "did-web-dba-foundation" / "postgres-ha" / "1.2.0" / "pages"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "pattern.md").write_text(
        "# Foundation pattern: Postgres HA monitoring taxonomy\n\n"
        "Distinguishes lag-magnitude from lag-rate alerts.",
        encoding="utf-8",
    )
    search_all = await _call(kb, "kb/search/0.1", {"query": "lag"})
    sources = {hit["source"] for hit in search_all["data"]["hits"]}
    assert "mine" in sources
    assert any(s.startswith("from:did-web-dba-foundation") for s in sources)

    # ── Step 6: lint the whole wiki ───────────────────────────────────
    lint_result = await _call(kb, "kb/lint/0.1", {})
    assert lint_result["ok"] is True
    assert lint_result["data"]["counts"]["error"] == 0
    assert lint_result["data"]["pages_scanned"] >= 4

    # ── Step 7: policy round-trip ─────────────────────────────────────
    before = await _call(kb, "kb/policy_get/0.1", {})
    assert before["data"]["policy"]["tier"] == "team"

    await _call(
        kb,
        "kb/policy_set/0.1",
        {"key": "consumer.redaction_level_min", "value": "strict"},
    )
    after = await _call(kb, "kb/policy_get/0.1", {})
    assert after["data"]["policy"]["consumer"]["redaction_level_min"] == "strict"
    disk_policy = yaml.safe_load((kb / ".kb" / "policy.yaml").read_text())
    assert disk_policy["consumer"]["redaction_level_min"] == "strict"

    # ── Step 8: the wiki skeleton we care about is intact ────────────
    for folder in ("patterns", "decisions", "failure-log", "entities"):
        assert (kb / "wiki" / folder).is_dir()
    assert (kb / ".kb" / "keys").is_dir()
    assert any((kb / ".kb" / "keys").glob("*.pub"))
