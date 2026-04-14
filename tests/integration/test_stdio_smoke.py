"""Transport-level smoke test: does `kb-mcp` start and speak MCP?

Launches the server as a subprocess with stdio transport, performs
the MCP initialize handshake via the SDK client, lists tools, and
calls `kb/policy_get/0.1`. Proves the console-script entry point is
wired correctly and the stdio surface is reachable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from kb_cli.init import scaffold


@pytest.mark.asyncio
async def test_server_starts_and_exposes_tools(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    scaffold(root=root, tier="individual", publisher_id="did:web:smoke.example")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kb_mcp_server", "--root", str(root)],
        env=None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert "kb/policy_get/0.1" in names
            assert "kb/search/0.1" in names
            assert "kb/publish/0.1" in names
            assert "kb/verify/0.1" in names
            assert len(names) >= 7

            result = await session.call_tool("kb/policy_get/0.1", {})
            assert result.content
            payload = json.loads(result.content[0].text)
            assert payload["ok"] is True
            assert payload["data"]["policy"]["tier"] == "individual"
