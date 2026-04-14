"""Consistent response envelope for every MCP tool in the kb/* surface.

Every tool returns a single `TextContent` whose text is a JSON object
with this shape:

    {
      "ok": <bool>,
      "data": <object|null>,
      "error": {"code": "...", "message": "..."} | null
    }

Agents parse this envelope once and branch on `ok`. Human operators
reading raw stdio also get something legible.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types


def ok(data: Any) -> list[types.TextContent]:
    payload = {"ok": True, "data": data, "error": None}
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def error(code: str, message: str, **extra: Any) -> list[types.TextContent]:
    err: dict[str, Any] = {"code": code, "message": message}
    err.update(extra)
    payload = {"ok": False, "data": None, "error": err}
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
