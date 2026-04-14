"""`kb/policy_set/0.1` — update one key in the KB policy document.

Only a single leaf key can be set per call. Nested paths are expressed
as a JSON pointer-style dotted path (for example `trust.model`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok

TOOL = types.Tool(
    name="kb/policy_set/0.1",
    description=(
        "Update a single leaf value in .kb/policy.yaml. The key is a "
        "dotted path (e.g. 'trust.model' or 'consumer.redaction_level_min'). "
        "Creates intermediate dicts if missing. Returns the new policy."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Dotted path to the leaf (e.g. 'trust.model').",
            },
            "value": {
                "description": "Any JSON-serializable value to assign at the path.",
            },
        },
        "required": ["key", "value"],
        "additionalProperties": False,
    },
)


def _set_nested(doc: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cursor: Any = doc
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    path = root / ".kb" / "policy.yaml"
    if not path.is_file():
        return error("policy_missing", f"No policy file at {path}")

    key = arguments.get("key")
    if not isinstance(key, str) or not key:
        return error("invalid_key", "Argument 'key' must be a non-empty string.")

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return error("policy_parse_error", str(exc))

    _set_nested(doc, key, arguments["value"])
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return ok({"policy": doc, "updated": key})
