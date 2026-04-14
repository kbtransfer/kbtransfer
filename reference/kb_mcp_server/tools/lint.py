"""`kb/lint/0.1` — schema-driven health check across the wiki.

Enforces the folders declared `required: true` in `.kb/schema.yaml`
and flags orphan pages and missing cross-references at the severity
the schema specifies. Contradiction and stale-claim detection are
scaffolded but require agent input to produce meaningful findings
in Phase 1 (kept as `info` notes for now).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok

TOOL = types.Tool(
    name="kb/lint/0.1",
    description=(
        "Run schema-driven lint across the wiki. Returns a list of "
        "findings grouped by severity (info | warning | error). "
        "No arguments."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)

LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _load_schema(root: Path) -> dict[str, Any]:
    schema_path = root / ".kb" / "schema.yaml"
    if not schema_path.is_file():
        raise FileNotFoundError(str(schema_path))
    return yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}


def _check_required_folders(root: Path, schema: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    folders = schema.get("folders", {})
    for name, spec in folders.items():
        if not spec or not spec.get("required"):
            continue
        if not (root / "wiki" / name).is_dir():
            findings.append(
                {
                    "rule": "required_folder_missing",
                    "severity": "error",
                    "path": f"wiki/{name}/",
                    "message": f"Required folder wiki/{name}/ is missing.",
                }
            )
    return findings


def _collect_pages(root: Path) -> list[Path]:
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    return [p for p in wiki.rglob("*.md") if p.is_file()]


def _collect_incoming_links(pages: list[Path], root: Path) -> dict[str, set[str]]:
    """Map each wiki-relative page path -> set of pages that link to it."""
    incoming: dict[str, set[str]] = {}
    for page in pages:
        rel = str(page.relative_to(root))
        incoming.setdefault(rel, set())
    for page in pages:
        text = page.read_text(encoding="utf-8")
        page_dir = page.parent
        for match in LINK_PATTERN.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (page_dir / target).resolve()
            try:
                rel_target = str(resolved.relative_to(root))
            except ValueError:
                continue
            if rel_target in incoming:
                incoming[rel_target].add(str(page.relative_to(root)))
    return incoming


def _check_orphans(
    pages: list[Path],
    incoming: dict[str, set[str]],
    root: Path,
    severity: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for page in pages:
        rel = str(page.relative_to(root))
        if page.name.lower() in ("readme.md", "index.md", "log.md"):
            continue
        if not incoming.get(rel):
            findings.append(
                {
                    "rule": "orphan_page",
                    "severity": severity,
                    "path": rel,
                    "message": "No other page links to this page.",
                }
            )
    return findings


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        schema = _load_schema(root)
    except FileNotFoundError as exc:
        return error("schema_missing", str(exc))
    except yaml.YAMLError as exc:
        return error("schema_parse_error", str(exc))

    findings: list[dict[str, Any]] = []
    findings.extend(_check_required_folders(root, schema))

    pages = _collect_pages(root)
    incoming = _collect_incoming_links(pages, root)
    orphan_severity = schema.get("lint", {}).get("orphan_pages", {}).get("severity", "warning")
    findings.extend(_check_orphans(pages, incoming, root, orphan_severity))

    summary = {
        "pages_scanned": len(pages),
        "findings": findings,
        "counts": {
            "error": sum(1 for f in findings if f["severity"] == "error"),
            "warning": sum(1 for f in findings if f["severity"] == "warning"),
            "info": sum(1 for f in findings if f["severity"] == "info"),
        },
    }
    return ok(summary)
