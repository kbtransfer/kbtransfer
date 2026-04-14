"""`kb/search/0.1` — text search across wiki/ and subscriptions/.

Results carry a `source` tag that marks each hit as either `mine`
(coming from the user's own wiki) or `from:<publisher>` (coming from a
subscribed pack). Implementation is plain Python: walks the two roots,
reads markdown, matches case-insensitively by substring or regex.

Ripgrep integration can replace this backend in a future revision
without changing the tool contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok

WIKI_ROOT = "wiki"
SUBSCRIPTIONS_ROOT = "subscriptions"
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
CONTEXT_CHARS = 80

TOOL = types.Tool(
    name="kb/search/0.1",
    description=(
        "Search markdown content under wiki/ and subscriptions/. "
        "Returns hits tagged with their source: 'mine' for the user's own "
        "wiki, 'from:<publisher>' for subscribed packs. Supports plain "
        "substring or regex queries; scope can be limited to one side."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex to search for.",
            },
            "regex": {
                "type": "boolean",
                "description": "Treat query as a regular expression.",
                "default": False,
            },
            "scope": {
                "type": "string",
                "enum": ["all", "mine", "subscriptions"],
                "description": "Which roots to search.",
                "default": "all",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of hits (1-{MAX_LIMIT}).",
                "default": DEFAULT_LIMIT,
                "minimum": 1,
                "maximum": MAX_LIMIT,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


def _compile_pattern(query: str, is_regex: bool) -> re.Pattern[str]:
    flags = re.IGNORECASE | re.MULTILINE
    return re.compile(query, flags) if is_regex else re.compile(re.escape(query), flags)


def _iter_markdown(base: Path):
    if not base.is_dir():
        return
    for candidate in sorted(base.rglob("*.md")):
        if candidate.is_file():
            yield candidate


def _source_tag_for_subscription(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root / SUBSCRIPTIONS_ROOT)
    except ValueError:
        return "from:unknown"
    return f"from:{rel.parts[0]}" if rel.parts else "from:unknown"


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    return text[left:right].replace("\n", " ").strip()


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _search_in(
    root: Path,
    base: Path,
    source_tag_fn,
    pattern: re.Pattern[str],
    limit: int,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for md_path in _iter_markdown(base):
        if len(hits) >= limit:
            break
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in pattern.finditer(text):
            hits.append(
                {
                    "path": str(md_path.relative_to(root)),
                    "source": source_tag_fn(md_path),
                    "line": _line_of_offset(text, match.start()),
                    "match": match.group(0),
                    "snippet": _snippet(text, match.start(), match.end()),
                }
            )
            if len(hits) >= limit:
                break
    return hits


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    query = arguments.get("query")
    if not isinstance(query, str) or not query:
        return error("invalid_query", "Argument 'query' must be a non-empty string.")
    is_regex = bool(arguments.get("regex", False))
    scope = arguments.get("scope", "all")
    limit = int(arguments.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        pattern = _compile_pattern(query, is_regex)
    except re.error as exc:
        return error("invalid_regex", str(exc))

    hits: list[dict[str, Any]] = []
    if scope in ("all", "mine"):
        hits.extend(
            _search_in(
                root,
                root / WIKI_ROOT,
                source_tag_fn=lambda _p: "mine",
                pattern=pattern,
                limit=limit - len(hits),
            )
        )
    if scope in ("all", "subscriptions") and len(hits) < limit:
        hits.extend(
            _search_in(
                root,
                root / SUBSCRIPTIONS_ROOT,
                source_tag_fn=lambda p: _source_tag_for_subscription(root, p),
                pattern=pattern,
                limit=limit - len(hits),
            )
        )
    return ok({"query": query, "scope": scope, "count": len(hits), "hits": hits})
