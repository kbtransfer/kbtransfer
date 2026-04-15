"""`kb/registry_submit/0.1` — push a signed tarball to an HTTPS registry (RFC-0002).

Thin wrapper over `HttpsRegistry.submit`. Reads the local tarball
(produced by `kb/publish/0.1`), POSTs it to the registry's
`/v0.1/submit` endpoint as `multipart/form-data`, and returns the
registry's structured response verbatim.

No signature work happens here — the pack is already signed before
publish. The registry re-runs the full verify pipeline against its
own trust store and accepts or rejects independently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_registry import HttpsRegistry, RegistryError, open_registry

TOOL = types.Tool(
    name="kb/registry_submit/0.1",
    description=(
        "Submit a signed pack tarball to an HTTPS kb-registry. Uploads "
        "the tarball under published/<pack>-<ver>.tar to the registry's "
        "/v0.1/submit endpoint; the registry re-verifies the pack and "
        "returns a structured accepted/rejected envelope. Only HTTPS "
        "(or git+https://) registries accept submissions."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "registry_url": {"type": "string"},
            "pack_tarball_path": {
                "type": "string",
                "description": (
                    "Path to the tarball to submit. Absolute, or relative "
                    "to the KB root (typically published/<pack>-<ver>.tar)."
                ),
            },
            "notes": {"type": "string", "default": ""},
            "bearer_token": {
                "type": "string",
                "description": "Required for private-tier registries.",
            },
        },
        "required": ["registry_url", "pack_tarball_path"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    registry_url = arguments.get("registry_url")
    tarball = arguments.get("pack_tarball_path")
    notes = arguments.get("notes", "") or ""
    bearer_token = arguments.get("bearer_token")

    if not isinstance(registry_url, str) or not registry_url:
        return error("invalid_registry_url", "registry_url must be a non-empty string.")
    if not isinstance(tarball, str) or not tarball:
        return error(
            "invalid_pack_tarball_path",
            "pack_tarball_path must be a non-empty string.",
        )

    tar_path = Path(tarball)
    if not tar_path.is_absolute():
        tar_path = (root / tar_path).resolve()
    if not tar_path.is_file():
        return error(
            "tarball_missing",
            f"no tarball at {tar_path}; run kb/publish/0.1 first.",
        )

    try:
        registry = open_registry(registry_url)
    except RegistryError as exc:
        return error("registry_open_failed", str(exc))
    if not isinstance(registry, HttpsRegistry):
        return error(
            "transport_unsupported",
            "submit requires an https:// or git+https:// registry URL; "
            f"got {registry_url!r}",
        )

    try:
        response = registry.submit(
            tar_path, notes=notes, bearer_token=bearer_token
        )
    except RegistryError as exc:
        return error("registry_submit_failed", str(exc))

    return ok(
        {
            "registry_url": registry_url,
            "tarball": str(tar_path),
            "response": response,
        }
    )
