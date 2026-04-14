"""`kb/ingest_source/0.1` — Karpathy-style source ingestion.

The agent calls this tool with a source (its content, plus optional
metadata). The tool:

1. Saves the source verbatim under `sources/` so it is immutable and
   available for future re-reads.
2. Returns a reading plan: the source content, a suggested set of
   wiki folders the agent should consider writing into, and a list
   of existing pages that might be relevant based on keyword overlap.

The tool does NOT write to the wiki itself. Composition is the
agent's job — the agent reads the plan, reads any suggested pages
with `kb/read/0.1`, and writes new or updated pages with
`kb/write/0.1`. This keeps the ingestion flow transparent and lets
the agent surface its reasoning before it commits to a structure.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok

DEFAULT_FOLDER_HINTS = ("patterns", "decisions", "failure-log", "entities")
KEYWORD_LIMIT = 20
STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
        "of", "to", "in", "for", "on", "with", "is", "are", "was", "were",
        "be", "being", "been", "by", "at", "as", "this", "that", "these",
        "those", "it", "its", "we", "you", "they", "them", "our", "your",
        "their", "from", "into", "over", "under", "up", "down", "out",
        "so", "not", "no", "do", "does", "did", "have", "has", "had",
    }
)

TOOL = types.Tool(
    name="kb/ingest_source/0.1",
    description=(
        "Persist a raw source under sources/ and return a reading plan: "
        "suggested wiki folders to write into, and existing pages that "
        "overlap with the source's keywords. Does not write to the wiki "
        "itself; the agent composes pages via kb/write/0.1."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Human-readable title or filename for the source.",
            },
            "content": {
                "type": "string",
                "description": "Raw source text. UTF-8.",
            },
            "origin": {
                "type": "string",
                "description": (
                    "Optional provenance marker: URL, ticket ID, conversation "
                    "reference, file path it came from."
                ),
            },
            "suggested_folders": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional folders the agent already believes this source "
                    "belongs in. Used to pre-fill the reading plan."
                ),
            },
        },
        "required": ["title", "content"],
        "additionalProperties": False,
    },
)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return slug[:60] if slug else "source"


def _save_source(root: Path, title: str, content: str, origin: str | None) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slug = _slugify(title)
    target = root / "sources" / f"{timestamp}-{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    header_lines = [f"# {title}"]
    frontmatter = {
        "ingested_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "title": title,
    }
    if origin:
        frontmatter["origin"] = origin
    body = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n"
    body += "\n".join(header_lines) + "\n\n" + content
    target.write_text(body, encoding="utf-8")
    return target


def _extract_keywords(text: str, limit: int = KEYWORD_LIMIT) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", text.lower())
    freq: dict[str, int] = {}
    for tok in tokens:
        if tok in STOPWORDS:
            continue
        freq[tok] = freq.get(tok, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]


def _find_related_pages(root: Path, keywords: list[str], limit: int = 10) -> list[dict[str, Any]]:
    wiki = root / "wiki"
    if not wiki.is_dir() or not keywords:
        return []
    scored: list[tuple[int, Path]] = []
    keyword_set = set(keywords)
    for page in wiki.rglob("*.md"):
        if not page.is_file():
            continue
        try:
            text = page.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            continue
        score = sum(1 for kw in keyword_set if kw in text)
        if score:
            scored.append((score, page))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [
        {"path": str(path.relative_to(root)), "keyword_overlap": score}
        for score, path in scored[:limit]
    ]


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    title = arguments.get("title")
    content = arguments.get("content")
    origin = arguments.get("origin")
    suggested = arguments.get("suggested_folders") or list(DEFAULT_FOLDER_HINTS)

    if not isinstance(title, str) or not title.strip():
        return error("invalid_title", "Argument 'title' must be a non-empty string.")
    if not isinstance(content, str) or not content:
        return error("invalid_content", "Argument 'content' must be a non-empty string.")

    saved = _save_source(root, title, content, origin if isinstance(origin, str) else None)
    keywords = _extract_keywords(content)
    related = _find_related_pages(root, keywords)

    plan = {
        "source_path": str(saved.relative_to(root)),
        "suggested_folders": suggested,
        "keywords": keywords,
        "related_pages": related,
        "next_steps": [
            "Read the saved source with kb/read/0.1 if you need the exact bytes.",
            "Read each related page with kb/read/0.1 before deciding whether to update it.",
            "Compose new or updated wiki pages with kb/write/0.1.",
            "Prefer additive updates; flag contradictions rather than overwriting.",
        ],
    }
    return ok(plan)
