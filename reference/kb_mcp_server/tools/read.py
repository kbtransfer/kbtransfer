"""`kb/read/0.1` — read a markdown page from the KB.

Path is relative to the KB root. Accepted roots are `wiki/`,
`subscriptions/`, `sources/`, and `drafts/`. Escapes outside the root
are rejected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok

READABLE_ROOTS = ("wiki", "subscriptions", "sources", "drafts")

TOOL = types.Tool(
    name="kb/read/0.1",
    description=(
        "Return the text content of a page under wiki/, subscriptions/, "
        "sources/, or drafts/. Path is relative to the KB root."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path inside the KB, e.g. 'wiki/patterns/foo.md'.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


def _validate_path(root: Path, requested: str) -> Path | None:
    candidate = (root / requested).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if not relative.parts or relative.parts[0] not in READABLE_ROOTS:
        return None
    return candidate


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    requested = arguments.get("path")
    if not isinstance(requested, str) or not requested:
        return error("invalid_path", "Argument 'path' must be a non-empty string.")
    resolved = _validate_path(root, requested)
    if resolved is None:
        return error(
            "forbidden_path",
            f"'{requested}' is not under a readable root ({', '.join(READABLE_ROOTS)}).",
        )
    if not resolved.is_file():
        return error("not_found", f"No file at {requested}")
    return ok(
        {
            "path": requested,
            "content": resolved.read_text(encoding="utf-8"),
            "size_bytes": resolved.stat().st_size,
        }
    )
