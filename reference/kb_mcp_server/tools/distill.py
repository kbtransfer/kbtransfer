"""`kb/distill/0.1` — run the tier-aware distillation pipeline on a draft.

Reads the draft's `pages/`, runs the regex scrubber plus whichever
checklist applies to the current tier, writes the scrubbed pages
back in place, and persists a `.distill-report.json` sibling so
`kb/publish/0.1` can populate the redaction attestation from the
exact report the agent saw.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_distiller import run_pipeline
from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)

TOOL = types.Tool(
    name="kb/distill/0.1",
    description=(
        "Run the tier-aware distillation pipeline against drafts/<pack_id>/pages/. "
        "Writes scrubbed markdown back in place and returns the checklist plus "
        "findings. A .distill-report.json is persisted for kb/publish/0.1."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "pack_id": {"type": "string"},
            "mode_override": {
                "type": "string",
                "enum": ["manual", "single-model", "dual-model"],
                "description": "Override the tier-implied distillation mode.",
            },
        },
        "required": ["pack_id"],
        "additionalProperties": False,
    },
)

REPORT_FILE = ".distill-report.json"


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    pack_id = arguments.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "Argument 'pack_id' must be a non-empty string.")

    draft_dir = root / "drafts" / pack_id
    pages_dir = draft_dir / "pages"
    if not draft_dir.is_dir() or not pages_dir.is_dir():
        return error("draft_missing", f"No draft at drafts/{pack_id}")

    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    pages: dict[str, str] = {}
    for md_path in sorted(pages_dir.glob("*.md")):
        pages[md_path.name] = md_path.read_text(encoding="utf-8")
    if not pages:
        return error("no_pages", f"drafts/{pack_id}/pages/ is empty.")

    mode_override = arguments.get("mode_override")
    mode_or_tier = mode_override if isinstance(mode_override, str) else ctx.tier

    result = run_pipeline(pages, tier_or_mode=mode_or_tier)

    for name, text in result.pages.items():
        (pages_dir / name).write_text(text, encoding="utf-8")

    report = {
        "mode": result.mode,
        "redaction_level": result.redaction_level,
        "categories_redacted": result.categories_redacted,
        "findings": [asdict(f) for f in result.findings],
        "checklist": result.checklist,
        "residual_risk_notes": result.residual_risk_notes,
        "needs_agent_input": result.needs_agent_input,
        "next_steps": result.next_steps,
    }
    (draft_dir / REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")

    return ok(
        {
            "pack_id": pack_id,
            "mode": result.mode,
            "redaction_level": result.redaction_level,
            "categories_redacted": result.categories_redacted,
            "finding_count": len(result.findings),
            "checklist": result.checklist,
            "residual_risk_notes": result.residual_risk_notes,
            "needs_agent_input": result.needs_agent_input,
            "next_steps": result.next_steps,
        }
    )
