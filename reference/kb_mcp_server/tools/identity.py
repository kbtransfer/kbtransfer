"""`kb/identity/0.1` — canonical whoami for the local KB.

Returns the publisher identity + active signing key so downstream
tools (AEAI adapter, etc.) can treat the KB server as the single
source of truth instead of re-assembling the same fields from
`.kb/tier.yaml` + `.kb/keys/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)
from kb_mcp_server.trust_store import load_trust_store

TOOL = types.Tool(
    name="kb/identity/0.1",
    description=(
        "Return the publisher identity, tier, and active signing key of "
        "this KB. Includes the publisher's own trust-store row if present "
        "so external callers can mirror it verbatim."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    store = load_trust_store(root)
    record = (store.get("publishers") or {}).get(ctx.publisher_id)
    trust_store_entry: dict[str, Any] | None = None
    if isinstance(record, dict):
        trust_store_entry = {
            "display_name": record.get("display_name", ""),
            "keys": [
                {
                    "key_id": k.get("key_id"),
                    "algorithm": k.get("algorithm", "ed25519"),
                    "public_key_hex": k.get("public_key_hex"),
                }
                for k in (record.get("keys") or [])
                if isinstance(k, dict)
            ],
        }

    return ok(
        {
            "publisher_id": ctx.publisher_id,
            "tier": ctx.tier,
            "key_id": ctx.key_id,
            "public_key_hex": ctx.public_key_hex,
            "display_name": (trust_store_entry or {}).get("display_name", ""),
            "trust_store_entry": trust_store_entry,
        }
    )
