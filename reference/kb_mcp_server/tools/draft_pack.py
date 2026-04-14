"""`kb/draft_pack/0.1` — scaffold a new pack draft from wiki pages.

The draft lands under `drafts/<pack_id>/` with the skeleton every
Phase 2 tool downstream expects:

    drafts/<pack_id>/
      pack.manifest.yaml       populated from args + publisher context
      README.md                minimal summary page
      pages/                   copied from selected wiki pages
      attestations/            four JSON stubs with kind-specific bodies

`kb/distill/0.1` runs the redaction pipeline against `pages/`.
`kb/publish/0.1` fills in the content_root, signs, and seals.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)

TOOL = types.Tool(
    name="kb/draft_pack/0.1",
    description=(
        "Create a new pack draft under drafts/<pack_id>/ by copying the "
        "listed wiki pages into pages/, writing pack.manifest.yaml, and "
        "seeding four attestation stubs. Does not sign or distill; those "
        "are kb/distill/0.1 and kb/publish/0.1."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "pack_id": {"type": "string"},
            "version": {"type": "string", "default": "0.1.0"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "namespace": {"type": "string"},
            "source_pages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Wiki-relative paths, e.g. ['wiki/patterns/foo.md'].",
            },
            "license_spdx": {
                "type": "string",
                "default": "Apache-2.0",
            },
            "force": {
                "type": "boolean",
                "default": False,
                "description": "Overwrite an existing draft with the same pack_id.",
            },
        },
        "required": ["pack_id", "title", "summary", "source_pages"],
        "additionalProperties": False,
    },
)


def _copy_pages(root: Path, source_pages: list[str], pages_dir: Path) -> list[str]:
    copied: list[str] = []
    wiki_root = (root / "wiki").resolve()
    for wiki_path in source_pages:
        src = (root / wiki_path).resolve()
        try:
            src.relative_to(wiki_root)
        except ValueError as exc:
            raise ValueError(f"{wiki_path!r} is not under wiki/") from exc
        if not src.is_file():
            raise FileNotFoundError(f"{wiki_path!r} does not exist")
        destination_name = src.name
        destination = pages_dir / destination_name
        if destination.exists():
            # Handle name collisions deterministically.
            stem, suffix = destination.stem, destination.suffix
            counter = 2
            while destination.exists():
                destination = pages_dir / f"{stem}-{counter}{suffix}"
                counter += 1
        shutil.copyfile(src, destination)
        copied.append(str(destination.name))
    return copied


def _write_manifest(
    draft_dir: Path,
    pack_id: str,
    version: str,
    title: str,
    summary: str,
    namespace: str,
    publisher_id: str,
    license_spdx: str,
    page_count: int,
) -> None:
    manifest = {
        "spec_version": "autoevolve-pack/0.1.1",
        "pack_id": pack_id,
        "version": version,
        "namespace": namespace or pack_id.rsplit(".", 1)[0] if "." in pack_id else pack_id,
        "publisher": {"id": publisher_id},
        "title": title,
        "summary": summary,
        "page_count": page_count,
        "total_size_bytes": 0,
        "license": {"spdx": license_spdx},
        "attestations": {
            "provenance": "attestations/provenance.json",
            "redaction": "attestations/redaction.json",
            "evaluation": "attestations/evaluation.json",
            "license": "attestations/license.json",
        },
        "policy_surface": [
            "redaction_level",
            "license_class",
            "evaluation_score",
            "publisher_identity",
        ],
    }
    (draft_dir / "pack.manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


def _write_attestation_stubs(draft_dir: Path) -> None:
    atts_dir = draft_dir / "attestations"
    atts_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("provenance", "redaction", "evaluation", "license"):
        stub_path = atts_dir / f"{kind}.json"
        if not stub_path.exists():
            stub_path.write_text("{}", encoding="utf-8")


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    pack_id = arguments.get("pack_id")
    title = arguments.get("title")
    summary = arguments.get("summary")
    source_pages = arguments.get("source_pages") or []
    version = arguments.get("version", "0.1.0")
    namespace = arguments.get("namespace", "")
    license_spdx = arguments.get("license_spdx", "Apache-2.0")
    force = bool(arguments.get("force", False))

    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "Argument 'pack_id' must be a non-empty string.")
    if not isinstance(title, str) or not title:
        return error("invalid_title", "Argument 'title' must be a non-empty string.")
    if not isinstance(summary, str) or not summary:
        return error("invalid_summary", "Argument 'summary' must be a non-empty string.")
    if not isinstance(source_pages, list) or not source_pages:
        return error(
            "no_source_pages", "Argument 'source_pages' must be a non-empty list."
        )

    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    draft_dir = root / "drafts" / pack_id
    if draft_dir.exists() and not force:
        return error(
            "draft_exists",
            f"drafts/{pack_id} already exists (use force=true to overwrite).",
        )
    if draft_dir.exists() and force:
        shutil.rmtree(draft_dir)
    draft_dir.mkdir(parents=True, exist_ok=True)

    pages_dir = draft_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    try:
        copied = _copy_pages(root, source_pages, pages_dir)
    except (ValueError, FileNotFoundError) as exc:
        shutil.rmtree(draft_dir, ignore_errors=True)
        return error("bad_source_page", str(exc))

    (draft_dir / "README.md").write_text(f"# {title}\n\n{summary}\n", encoding="utf-8")
    _write_manifest(
        draft_dir,
        pack_id=pack_id,
        version=version,
        title=title,
        summary=summary,
        namespace=namespace,
        publisher_id=ctx.publisher_id,
        license_spdx=license_spdx,
        page_count=len(copied),
    )
    _write_attestation_stubs(draft_dir)

    return ok(
        {
            "pack_id": pack_id,
            "version": version,
            "draft_path": f"drafts/{pack_id}",
            "pages_copied": copied,
            "next_steps": [
                "Edit or trim the copied pages under drafts/<pack_id>/pages/ if needed.",
                "Call kb/distill/0.1 to run the redaction pipeline.",
                "Call kb/publish/0.1 once the distiller checklist is satisfied.",
            ],
        }
    )
