"""`kb/registry_describe/0.1` — return a kb-registry's self-description."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_registry import RegistryError, open_registry

TOOL = types.Tool(
    name="kb/registry_describe/0.1",
    description=(
        "Open the registry at `registry_url` and return its "
        "self-description (publisher count, pack count, updated_at)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "registry_url": {"type": "string"},
        },
        "required": ["registry_url"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    url = arguments.get("registry_url")
    if not isinstance(url, str) or not url:
        return error("invalid_registry_url", "registry_url must be a non-empty string.")
    try:
        registry = open_registry(url)
        description = registry.describe()
    except RegistryError as exc:
        return error("registry_describe_failed", str(exc))
    return ok(description)
