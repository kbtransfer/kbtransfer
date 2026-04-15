"""`kb/trust_add/0.1` — programmatic trust-store upsert.

Wraps `register_publisher_key` with conflict detection so callers
hitting a pre-existing (publisher_id, key_id) pair under a different
public key get an explicit `key_change_detected` error unless
`confirm_replace: true` is set. Without the handler an AEAI-style
caller would have to parse + edit `.kb/trust-store.yaml` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.trust_store import (
    load_trust_store,
    register_publisher_key,
)

TOOL = types.Tool(
    name="kb/trust_add/0.1",
    description=(
        "Upsert a publisher's keys into .kb/trust-store.yaml. Rejects "
        "any key_id already bound to a different public key unless "
        "confirm_replace is true."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "publisher_id": {"type": "string"},
            "display_name": {"type": "string"},
            "keys": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key_id": {"type": "string"},
                        "public_key_hex": {"type": "string"},
                        "algorithm": {"type": "string", "default": "ed25519"},
                    },
                    "required": ["key_id", "public_key_hex"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
            "confirm_replace": {"type": "boolean", "default": False},
        },
        "required": ["publisher_id", "keys"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    publisher_id = arguments.get("publisher_id")
    keys = arguments.get("keys") or []
    display_name = arguments.get("display_name")
    confirm_replace = bool(arguments.get("confirm_replace", False))

    if not isinstance(publisher_id, str) or not publisher_id:
        return error("invalid_publisher_id", "publisher_id must be a non-empty string.")
    if not isinstance(keys, list) or not keys:
        return error("invalid_keys", "keys must be a non-empty list.")

    store = load_trust_store(root)
    existing = (store.get("publishers") or {}).get(publisher_id) or {}
    existing_keys = {
        k.get("key_id"): k.get("public_key_hex")
        for k in (existing.get("keys") or [])
        if isinstance(k, dict)
    }

    conflicts: list[dict[str, str]] = []
    for entry in keys:
        if not isinstance(entry, dict):
            return error("invalid_keys", "each keys[] entry must be an object.")
        key_id = entry.get("key_id")
        pubhex = entry.get("public_key_hex")
        if not isinstance(key_id, str) or not isinstance(pubhex, str):
            return error("invalid_keys", "each key requires key_id and public_key_hex.")
        algorithm = entry.get("algorithm") or "ed25519"
        if algorithm != "ed25519":
            return error(
                "unsupported_algorithm",
                f"only ed25519 is supported, got {algorithm!r}.",
            )
        prior = existing_keys.get(key_id)
        if prior and prior != pubhex:
            conflicts.append(
                {
                    "key_id": key_id,
                    "existing_public_key_hex": prior,
                    "requested_public_key_hex": pubhex,
                }
            )

    if conflicts and not confirm_replace:
        return error(
            "key_change_detected",
            f"{len(conflicts)} key(s) already bound to a different public key; "
            "re-run with confirm_replace=true to overwrite.",
            conflicts=conflicts,
        )

    added: list[str] = []
    replaced: list[str] = []
    unchanged: list[str] = []
    for entry in keys:
        key_id = entry["key_id"]
        pubhex = entry["public_key_hex"]
        prior = existing_keys.get(key_id)
        register_publisher_key(
            root,
            publisher_id=publisher_id,
            key_id=key_id,
            public_key_hex=pubhex,
            display_name=display_name if isinstance(display_name, str) else None,
            origin="kb/trust_add/0.1",
        )
        if prior is None:
            added.append(key_id)
        elif prior == pubhex:
            unchanged.append(key_id)
        else:
            replaced.append(key_id)

    return ok(
        {
            "publisher_id": publisher_id,
            "added": added,
            "replaced": replaced,
            "unchanged": unchanged,
        }
    )
