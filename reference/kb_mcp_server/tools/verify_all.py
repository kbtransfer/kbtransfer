"""`kb/verify_all/0.1` — re-verify every installed subscription.

Walks `subscriptions/<did-safe>/<pack_id>/<version>/` and runs the
standard `verify_pack` against the local trust store for each. Each
entry gets a status in {verified, signature_failed, missing_key,
corrupt}. Callers can scope the walk to a single publisher with the
optional `publisher_id` argument.

This is the batch cousin of `kb/verify/0.1`; it's called by external
consumers that need per-subscription freshness without paying the
cost of enumerating the filesystem and dispatching `kb/verify/0.1`
one-by-one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import ok
from kb_mcp_server.trust_store import resolver_from_trust_store
from kb_pack import did_to_safe_path, load_manifest, verify_pack

TOOL = types.Tool(
    name="kb/verify_all/0.1",
    description=(
        "Re-verify every installed subscription against the local trust "
        "store. Returns a row per {publisher, pack, version} with a "
        "status code and the verification step that failed (if any)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "publisher_id": {
                "type": "string",
                "description": "Optional — scope the walk to this publisher.",
            },
        },
        "additionalProperties": False,
    },
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    subs_root = root / "subscriptions"
    publisher_filter = arguments.get("publisher_id")
    scoped_dir: Path | None = None
    if isinstance(publisher_filter, str) and publisher_filter:
        try:
            scoped_dir = subs_root / did_to_safe_path(publisher_filter)
        except ValueError:
            scoped_dir = None

    results: list[dict[str, Any]] = []
    if not subs_root.is_dir():
        return ok(
            {
                "verified_at": _now_iso(),
                "subscriptions": results,
                "summary": _empty_summary(),
            }
        )

    resolver = resolver_from_trust_store(root)

    if scoped_dir is not None:
        publisher_dirs = [scoped_dir] if scoped_dir.is_dir() else []
    else:
        publisher_dirs = sorted(p for p in subs_root.iterdir() if p.is_dir())

    for pub_dir in publisher_dirs:
        for pack_dir in sorted(p for p in pub_dir.iterdir() if p.is_dir()):
            for version_dir in sorted(p for p in pack_dir.iterdir() if p.is_dir()):
                results.append(_verify_one(root, version_dir, resolver))

    summary = _summarize(results)
    return ok(
        {
            "verified_at": _now_iso(),
            "subscriptions": results,
            "summary": summary,
        }
    )


def _verify_one(
    kb_root: Path,
    version_dir: Path,
    resolver: Any,
) -> dict[str, Any]:
    publisher_id = ""
    pack_id = version_dir.parent.name
    version = version_dir.name
    try:
        manifest = load_manifest(version_dir)
        publisher_id = manifest.publisher_id
    except Exception as exc:
        return {
            "publisher_id": publisher_id,
            "pack_id": pack_id,
            "version": version,
            "installed_at": str(version_dir.relative_to(kb_root)),
            "status": "corrupt",
            "step": "manifest",
            "message": f"manifest unreadable: {exc}",
        }

    result = verify_pack(version_dir, resolver)
    if result.ok:
        return {
            "publisher_id": publisher_id,
            "pack_id": pack_id,
            "version": version,
            "installed_at": str(version_dir.relative_to(kb_root)),
            "status": "verified",
            "content_root": result.content_root,
            "pack_root": result.pack_root,
        }

    status = "signature_failed"
    if result.step == "S3b" and "untrusted" in result.message:
        status = "missing_key"
    elif result.step in ("S2", "S3a", "S3c"):
        status = "corrupt"

    return {
        "publisher_id": publisher_id,
        "pack_id": pack_id,
        "version": version,
        "installed_at": str(version_dir.relative_to(kb_root)),
        "status": status,
        "step": result.step,
        "message": result.message,
    }


def _empty_summary() -> dict[str, int]:
    return {
        "total": 0,
        "verified": 0,
        "signature_failed": 0,
        "missing_key": 0,
        "corrupt": 0,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = _empty_summary()
    summary["total"] = len(results)
    for row in results:
        status = row.get("status", "corrupt")
        if status in summary:
            summary[status] += 1
    return summary
