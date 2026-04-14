"""Tool registry for the kb/* MCP surface (Phase 1).

Each tool module exposes two module-level attributes:

- `TOOL`: an `mcp.types.Tool` describing the tool to the client.
- `HANDLER`: an async callable `(root, arguments) -> list[TextContent]`.

The registry in this module is the single import point for `server.py`.
Adding a new tool means adding its module to `_MODULES` below.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import mcp.types as types

from . import (
    ingest_source as _ingest_source,
    lint as _lint,
    policy_get as _policy_get,
    policy_set as _policy_set,
    read as _read,
    search as _search,
    write as _write,
)

Handler = Callable[[Path, dict[str, Any]], Awaitable[list[types.TextContent]]]

_MODULES = [
    _search,
    _read,
    _write,
    _ingest_source,
    _lint,
    _policy_get,
    _policy_set,
]

TOOLS: list[types.Tool] = [mod.TOOL for mod in _MODULES]
HANDLERS: dict[str, Handler] = {mod.TOOL.name: mod.HANDLER for mod in _MODULES}
