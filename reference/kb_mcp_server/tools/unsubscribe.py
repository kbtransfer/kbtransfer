"""`kb/unsubscribe/0.1` — remove an installed subscription.

Subscriptions land at `subscriptions/<publisher-did-safe>/<pack_id>/<version>/`
with files installed as 0o444 and directories as 0o555 (see follow-up
#5 in commit a2c8f0c). A plain `rmtree` fails on such a tree, so this
handler restores write bits first, then removes.

Modes:
- version provided  → remove that single version directory.
- version omitted   → remove all versions of that pack (the pack dir).

The publisher directory is cleaned up when it becomes empty, so a
fresh subscribe flow starts from a clean layout.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.subscription_fs import make_tree_writable
from kb_pack import did_to_safe_path

TOOL = types.Tool(
    name="kb/unsubscribe/0.1",
    description=(
        "Remove an installed subscription. Restores write bits on the "
        "read-only subscription tree before deletion. When `version` is "
        "omitted, all versions of the pack for that publisher are removed."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "publisher_id": {"type": "string"},
            "pack_id": {"type": "string"},
            "version": {"type": "string"},
        },
        "required": ["publisher_id", "pack_id"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    publisher_id = arguments.get("publisher_id")
    pack_id = arguments.get("pack_id")
    version = arguments.get("version")

    if not isinstance(publisher_id, str) or not publisher_id:
        return error("invalid_publisher_id", "publisher_id must be a non-empty string.")
    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "pack_id must be a non-empty string.")
    if version is not None and (not isinstance(version, str) or not version):
        return error("invalid_version", "version must be a non-empty string or omitted.")

    try:
        did_safe = did_to_safe_path(publisher_id)
    except ValueError as exc:
        return error("invalid_publisher_id", str(exc))

    pack_root = root / "subscriptions" / did_safe / pack_id
    if version is not None:
        target = pack_root / version
    else:
        target = pack_root

    if not target.exists():
        return ok(
            {
                "publisher_id": publisher_id,
                "pack_id": pack_id,
                "version": version,
                "removed": [],
                "already_absent": True,
            }
        )

    removed: list[str] = []
    if target.is_dir():
        make_tree_writable(target)
        for child in sorted(target.rglob("*")):
            if child.is_file():
                removed.append(str(child.relative_to(root)))
        shutil.rmtree(target)
        if target is not pack_root and pack_root.is_dir() and not any(pack_root.iterdir()):
            pack_root.rmdir()
        publisher_dir = pack_root.parent
        if publisher_dir.is_dir() and not any(publisher_dir.iterdir()):
            publisher_dir.rmdir()

    return ok(
        {
            "publisher_id": publisher_id,
            "pack_id": pack_id,
            "version": version,
            "removed": removed,
            "already_absent": False,
        }
    )
