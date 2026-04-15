"""`kb/registry_mirror/0.1` — copy a locally-published pack into a filesystem registry.

Filesystem-only counterpart of `kb/registry_submit/0.1`: no HTTP,
no validation step (the signature is already valid because it was
just produced by `kb/publish/0.1`). Use this to populate a local
sample-registry or a git-hosted registry working copy before
committing + pushing.

For HTTPS or git+https targets use `kb/registry_submit/0.1` instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mcp.types as types

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)
from kb_pack import did_to_safe_path
from kb_registry.index import write_index

TOOL = types.Tool(
    name="kb/registry_mirror/0.1",
    description=(
        "Copy a published tarball into a filesystem kb-registry layout. "
        "Writes packs/<pack_id>/<version>.tar, upserts "
        "publishers/<did-safe>/keys.json with this KB's active key, "
        "rebuilds index.json."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "pack_id": {"type": "string"},
            "registry_root": {
                "type": "string",
                "description": (
                    "Absolute path (or relative to the KB root) of the "
                    "filesystem kb-registry to mirror into."
                ),
            },
            "version": {
                "type": "string",
                "description": "Optional — if omitted, mirror every published tarball for pack_id.",
            },
        },
        "required": ["pack_id", "registry_root"],
        "additionalProperties": False,
    },
)


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    pack_id = arguments.get("pack_id")
    registry_root_arg = arguments.get("registry_root")
    version = arguments.get("version")

    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "pack_id must be a non-empty string.")
    if not isinstance(registry_root_arg, str) or not registry_root_arg:
        return error("invalid_registry_root", "registry_root must be a non-empty string.")
    if version is not None and (not isinstance(version, str) or not version):
        return error("invalid_version", "version must be a non-empty string or omitted.")

    registry_root = Path(registry_root_arg)
    if not registry_root.is_absolute():
        registry_root = (root / registry_root).resolve()
    if not registry_root.is_dir():
        return error(
            "registry_not_found",
            f"registry root does not exist or is not a directory: {registry_root}",
        )

    published_dir = root / "published"
    if version:
        candidates = [published_dir / f"{pack_id}-{version}.tar"]
    else:
        candidates = sorted(published_dir.glob(f"{pack_id}-*.tar"))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return error(
            "no_tarballs_found",
            f"no published tarballs matched pack_id={pack_id!r}"
            + (f" version={version!r}" if version else ""),
        )

    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    publisher_keys_path = _upsert_publisher_keys(registry_root, ctx)

    mirrored: list[dict[str, str]] = []
    for tar_path in candidates:
        ver = _extract_version(tar_path.name, pack_id)
        if ver is None:
            continue
        dest_dir = registry_root / "packs" / pack_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{ver}.tar"
        dest.write_bytes(tar_path.read_bytes())
        mirrored.append(
            {
                "version": ver,
                "source": str(tar_path.relative_to(root)),
                "destination": str(dest.relative_to(registry_root)),
            }
        )

    if not mirrored:
        return error(
            "no_tarballs_mirrored",
            "tarball filenames did not match the expected <pack_id>-<version>.tar pattern.",
        )

    index_path = write_index(registry_root)

    return ok(
        {
            "pack_id": pack_id,
            "registry_root": str(registry_root),
            "publisher_id": ctx.publisher_id,
            "publisher_keys": str(publisher_keys_path.relative_to(registry_root)),
            "mirrored": mirrored,
            "index": str(index_path.relative_to(registry_root)),
        }
    )


def _upsert_publisher_keys(registry_root: Path, ctx: Any) -> Path:
    did_safe = did_to_safe_path(ctx.publisher_id)
    pub_dir = registry_root / "publishers" / did_safe
    pub_dir.mkdir(parents=True, exist_ok=True)
    keys_file = pub_dir / "keys.json"
    doc: dict[str, Any] = {
        "publisher_id": ctx.publisher_id,
        "display_name": "",
        "keys": [],
    }
    if keys_file.is_file():
        try:
            doc = json.loads(keys_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    keys = doc.setdefault("keys", [])
    for key in keys:
        if isinstance(key, dict) and key.get("key_id") == ctx.key_id:
            if key.get("public_key_hex") != ctx.public_key_hex:
                key["public_key_hex"] = ctx.public_key_hex
            break
    else:
        keys.append(
            {
                "key_id": ctx.key_id,
                "algorithm": "ed25519",
                "public_key_hex": ctx.public_key_hex,
            }
        )
    doc.setdefault("publisher_id", ctx.publisher_id)
    keys_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return keys_file


def _extract_version(filename: str, pack_id: str) -> str | None:
    prefix = f"{pack_id}-"
    if not filename.startswith(prefix) or not filename.endswith(".tar"):
        return None
    return filename[len(prefix) : -len(".tar")]
