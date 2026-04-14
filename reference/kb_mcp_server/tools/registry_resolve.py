"""`kb/registry_resolve/0.1` — resolve a pack_id + constraint against a registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_registry import RegistryError, open_registry

TOOL = types.Tool(
    name="kb/registry_resolve/0.1",
    description=(
        "Resolve a pack_id + version constraint against a registry URL "
        "(file:// or bare path in Phase 3 v1). Returns the best matching "
        "version plus fetch metadata."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "registry_url": {"type": "string"},
            "pack_id": {"type": "string"},
            "constraint": {"type": "string", "default": "*"},
        },
        "required": ["registry_url", "pack_id"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    url = arguments.get("registry_url")
    pack_id = arguments.get("pack_id")
    constraint = arguments.get("constraint", "*")
    if not isinstance(url, str) or not url:
        return error("invalid_registry_url", "registry_url must be a non-empty string.")
    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "pack_id must be a non-empty string.")
    try:
        registry = open_registry(url)
        resolved = registry.resolve(pack_id, constraint)
    except RegistryError as exc:
        return error("registry_resolve_failed", str(exc))
    return ok(
        {
            "pack_id": resolved.pack_id,
            "version": resolved.version,
            "publisher_id": resolved.publisher_id,
            "tar_relative_path": resolved.tar_relative_path,
            "sha256": resolved.sha256,
            "registry_url": url,
        }
    )
