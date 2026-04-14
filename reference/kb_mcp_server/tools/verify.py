"""`kb/verify/0.1` — stand-alone verification of a pack directory.

Runs the seven-step spec procedure against a pack that already
lives under `subscriptions/` (typical case) or a pack the user
points at directly. Useful for re-checking after a trust-store
edit or as a diagnostic after a failed subscribe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.trust_store import resolver_from_trust_store
from kb_pack import verify_pack

TOOL = types.Tool(
    name="kb/verify/0.1",
    description=(
        "Re-run the seven-step verification against an installed pack "
        "directory. 'path' is relative to the KB root; typically "
        "'subscriptions/<did>/<pack_id>/<version>'."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    requested = arguments.get("path")
    if not isinstance(requested, str) or not requested:
        return error("invalid_path", "Argument 'path' must be a non-empty string.")

    pack_dir = (root / requested).resolve()
    try:
        pack_dir.relative_to(root)
    except ValueError:
        return error("forbidden_path", f"{requested!r} escapes the KB root.")
    if not pack_dir.is_dir():
        return error("not_found", f"No directory at {requested}")

    resolver = resolver_from_trust_store(root)
    result = verify_pack(pack_dir, resolver)
    payload = {
        "ok": result.ok,
        "step": result.step,
        "message": result.message,
        "content_root": result.content_root,
        "pack_root": result.pack_root,
    }
    if result.attestations:
        payload["attestation_kinds"] = sorted(result.attestations.keys())
    return ok(payload) if result.ok else error(
        f"verify_failed_{result.step}",
        result.message,
        content_root=result.content_root,
        pack_root=result.pack_root,
    )
