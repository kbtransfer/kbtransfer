"""`kb/registry_search/0.1` — federated search across one or more registries.

Consumer supplies a list of registry URLs; the tool queries each
in order and concatenates the results, annotating each hit with the
registry it came from. Useful before calling kb/subscribe/0.1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_registry import RegistryError, open_registry

DEFAULT_LIMIT = 20

TOOL = types.Tool(
    name="kb/registry_search/0.1",
    description=(
        "Search one or more kb-registries for packs matching a query. "
        "Hits are annotated with the registry URL they came from."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "registry_urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "query": {"type": "string"},
            "limit_per_registry": {
                "type": "integer",
                "default": DEFAULT_LIMIT,
                "minimum": 1,
                "maximum": 200,
            },
        },
        "required": ["registry_urls", "query"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    urls = arguments.get("registry_urls") or []
    query = arguments.get("query")
    limit = int(arguments.get("limit_per_registry", DEFAULT_LIMIT))
    if not isinstance(urls, list) or not urls:
        return error("invalid_urls", "registry_urls must be a non-empty list.")
    if not isinstance(query, str) or not query:
        return error("invalid_query", "query must be a non-empty string.")

    aggregated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for url in urls:
        if not isinstance(url, str) or not url:
            continue
        try:
            registry = open_registry(url)
            hits = registry.search(query, limit=limit)
        except RegistryError as exc:
            errors.append({"registry_url": url, "error": str(exc)})
            continue
        for hit in hits:
            hit["registry_url"] = url
        aggregated.extend(hits)

    return ok(
        {
            "query": query,
            "hit_count": len(aggregated),
            "hits": aggregated,
            "errors": errors,
        }
    )
