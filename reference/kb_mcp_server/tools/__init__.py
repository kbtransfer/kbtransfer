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
    distill as _distill,
    draft_pack as _draft_pack,
    identity as _identity,
    ingest_source as _ingest_source,
    lint as _lint,
    policy_get as _policy_get,
    policy_set as _policy_set,
    publish as _publish,
    read as _read,
    registry_describe as _registry_describe,
    registry_mirror as _registry_mirror,
    registry_resolve as _registry_resolve,
    registry_search as _registry_search,
    registry_submit as _registry_submit,
    search as _search,
    subscribe as _subscribe,
    trust_add as _trust_add,
    unsubscribe as _unsubscribe,
    verify as _verify,
    verify_all as _verify_all,
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
    _draft_pack,
    _distill,
    _publish,
    _subscribe,
    _unsubscribe,
    _verify,
    _registry_describe,
    _registry_resolve,
    _registry_search,
    _registry_submit,
    _registry_mirror,
    _trust_add,
    _identity,
    _verify_all,
]

TOOLS: list[types.Tool] = [mod.TOOL for mod in _MODULES]
HANDLERS: dict[str, Handler] = {mod.TOOL.name: mod.HANDLER for mod in _MODULES}
