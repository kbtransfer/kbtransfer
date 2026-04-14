"""Stdio MCP server exposing the Phase 1 kb/* tool surface."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from kb_mcp_server.envelope import error
from kb_mcp_server.kb_root import resolve_kb_root
from kb_mcp_server.tools import HANDLERS, TOOLS

logger = logging.getLogger("kb_mcp_server")


def build_server(kb_root: Path) -> Server:
    server = Server("kb-mcp-server")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        handler = HANDLERS.get(name)
        if handler is None:
            return error("unknown_tool", f"No tool named {name}")
        try:
            return await handler(kb_root, arguments or {})
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return error("tool_exception", f"{type(exc).__name__}: {exc}")

    return server


async def _run(kb_root: Path) -> None:
    server = build_server(kb_root)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def serve(explicit_root: str | Path | None = None) -> None:
    kb_root = resolve_kb_root(explicit_root)
    logger.info("Serving KB at %s", kb_root)
    asyncio.run(_run(kb_root))
