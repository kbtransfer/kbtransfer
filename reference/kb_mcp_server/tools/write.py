"""`kb/write/0.1` — create or update a wiki page (or a draft/source).

The tool rejects writes outside `wiki/`, `drafts/`, and `sources/`.
It rejects writes to `subscriptions/` unconditionally — subscribed
packs are read-only per the design decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok

WRITABLE_ROOTS = ("wiki", "drafts", "sources")

TOOL = types.Tool(
    name="kb/write/0.1",
    description=(
        "Create or overwrite a file under wiki/, drafts/, or sources/. "
        "Subscriptions are read-only and cannot be written. Parent "
        "directories are created as needed."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path inside the KB, e.g. 'wiki/patterns/foo.md'.",
            },
            "content": {
                "type": "string",
                "description": "Full text content to write. UTF-8 encoded.",
            },
            "append_log": {
                "type": "boolean",
                "description": (
                    "If true, append a one-line entry to wiki/log.md noting "
                    "the write. Defaults to true for wiki/ paths."
                ),
                "default": True,
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
)


def _validate_path(root: Path, requested: str) -> Path | None:
    candidate = (root / requested).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if not relative.parts or relative.parts[0] not in WRITABLE_ROOTS:
        return None
    return candidate


def _append_log(root: Path, path_relative: str) -> None:
    log = root / "wiki" / "log.md"
    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    entry = f"\n## {timestamp} — wrote {path_relative}\n- pages_touched: [{path_relative}]\n"
    if log.is_file():
        log.write_text(log.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        log.write_text(entry, encoding="utf-8")


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    requested = arguments.get("path")
    content = arguments.get("content")
    if not isinstance(requested, str) or not requested:
        return error("invalid_path", "Argument 'path' must be a non-empty string.")
    if not isinstance(content, str):
        return error("invalid_content", "Argument 'content' must be a string.")

    resolved = _validate_path(root, requested)
    if resolved is None:
        return error(
            "forbidden_path",
            f"'{requested}' is not under a writable root ({', '.join(WRITABLE_ROOTS)}).",
        )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")

    append_log = arguments.get("append_log")
    if append_log is None:
        append_log = requested.startswith("wiki/") and not requested.endswith("log.md")
    if append_log:
        _append_log(root, requested)

    return ok(
        {
            "path": requested,
            "bytes_written": len(content.encode("utf-8")),
            "logged": bool(append_log),
        }
    )
