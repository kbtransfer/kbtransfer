"""`kb/policy_get/0.1` — return the current KB policy document."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok

TOOL = types.Tool(
    name="kb/policy_get/0.1",
    description=(
        "Return the current consumer + publisher policy for this KB, "
        "parsed from .kb/policy.yaml. No arguments."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    path = root / ".kb" / "policy.yaml"
    if not path.is_file():
        return error("policy_missing", f"No policy file at {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return error("policy_parse_error", str(exc))
    return ok({"policy": doc, "path": str(path.relative_to(root))})
