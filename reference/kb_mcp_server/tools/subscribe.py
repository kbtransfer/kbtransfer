"""`kb/subscribe/0.1` — fetch, verify, and install a pack as a subscription.

Input is a local path to either a pack tarball (`.tar`) or an already-
extracted pack directory. Remote fetch (HTTP, git, file://) is
Phase 3 work; Phase 2 exercises the full verify + install flow
against a local artifact.

Flow:

1. Resolve the source into a working directory (extract the tar
   into a temp area if needed).
2. Read the publisher id from the pack's manifest and the pack's
   own `signatures/publisher.pubkey`.
3. If the consumer's trust model is TOFU (individual / team tiers),
   register the publisher's pubkey in `.kb/trust-store.yaml` before
   verification so the signatures can be checked. Enterprise tier
   requires the publisher to already be present; unknown publisher
   means rejection.
4. Run `kb_pack.verify_pack` via the trust-store resolver.
5. On OK, move the directory into
   `subscriptions/<publisher-id>/<pack_id>/<version>/` and return a
   summary. On failure, emit the failing step and reason without
   installing anything.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)
from kb_mcp_server.trust_store import (
    register_publisher_key,
    resolver_from_trust_store,
)
from kb_pack import did_to_safe_path, verify_pack

TOOL = types.Tool(
    name="kb/subscribe/0.1",
    description=(
        "Subscribe to a pack. Provide either a local `source` path (tarball "
        "or directory) OR a `{registry_url, pack_id, constraint}` triple to "
        "fetch from a kb-registry. The pack is verified against the trust "
        "store; on success it lands under subscriptions/<did>/<pack_id>/"
        "<version>/ as read-only content. TOFU tiers register newly-seen "
        "publisher keys automatically."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Local path to a .tar pack or an extracted pack directory.",
            },
            "registry_url": {
                "type": "string",
                "description": "Registry URL (file:// or bare path). Alternative to `source`.",
            },
            "pack_id": {
                "type": "string",
                "description": "Required when subscribing via registry_url.",
            },
            "constraint": {
                "type": "string",
                "default": "*",
                "description": "Version constraint (semver). Defaults to latest.",
            },
            "display_name": {
                "type": "string",
                "description": "Optional display name to record in the trust store.",
            },
        },
        "additionalProperties": False,
    },
)


def _extract_tarball(tar_path: Path, dest: Path) -> Path:
    with tarfile.open(tar_path, "r") as tar:
        # Python 3.12+ strict filter rejects anything outside dest.
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)  # older Pythons
    # Expect a single top-level directory in the archive.
    entries = [p for p in dest.iterdir() if p.is_dir()]
    if len(entries) != 1:
        raise ValueError(
            f"Tarball did not contain a single top-level directory (found {len(entries)})"
        )
    return entries[0]


def _policy_allows_tofu(root: Path) -> bool:
    policy = yaml.safe_load((root / ".kb" / "policy.yaml").read_text(encoding="utf-8")) or {}
    trust = policy.get("trust") or {}
    if trust.get("tofu_enabled") is False:
        return False
    return trust.get("model") == "tofu"


def _read_manifest(pack_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((pack_dir / "pack.manifest.yaml").read_text(encoding="utf-8"))


def _bundled_pubkey_hex(pack_dir: Path) -> str:
    return (pack_dir / "signatures" / "publisher.pubkey").read_bytes().hex()


def _chmod_tree_read_only(root: Path) -> None:
    # Defense-in-depth atop the MCP server's write-rejection for
    # `subscriptions/*`: make the installed pack physically read-only so
    # an unrelated tool with filesystem access cannot silently mutate it.
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(Path(dirpath) / name, 0o444)
        for name in dirnames:
            os.chmod(Path(dirpath) / name, 0o555)
    os.chmod(root, 0o555)


def _chmod_tree_writable(root: Path) -> None:
    # Restore write bits so `shutil.rmtree` can replace a previous
    # read-only install during re-subscribe.
    for dirpath, _dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for name in filenames:
            try:
                os.chmod(Path(dirpath) / name, 0o644)
            except OSError:
                pass
    try:
        os.chmod(root, 0o755)
    except OSError:
        pass


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    source = arguments.get("source")
    registry_url = arguments.get("registry_url")
    display_name = arguments.get("display_name")

    # Resolve registry-mode subscribe into an equivalent local path.
    fetched_dir: Path | None = None
    fetched_scratch: str | None = None
    if isinstance(registry_url, str) and registry_url:
        pack_id = arguments.get("pack_id")
        constraint = arguments.get("constraint", "*")
        if not isinstance(pack_id, str) or not pack_id:
            return error(
                "invalid_pack_id",
                "pack_id is required when subscribing via registry_url.",
            )
        from kb_registry import RegistryError, open_registry

        try:
            registry = open_registry(registry_url)
            resolved = registry.resolve(pack_id, constraint)
            fetched_scratch = tempfile.mkdtemp(prefix="kbsub-reg-")
            fetched_dir = registry.fetch(
                resolved.pack_id, resolved.version, Path(fetched_scratch)
            )
        except RegistryError as exc:
            return error("registry_resolve_failed", str(exc))
        source_path = fetched_dir
    else:
        if not isinstance(source, str) or not source:
            return error(
                "invalid_source",
                "Provide either 'source' (local path) or 'registry_url' + 'pack_id'.",
            )
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists():
            return error("source_not_found", f"No file or directory at {source_path}")

    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    # Stage the pack in a temp directory so a failed verification leaves
    # nothing under subscriptions/.
    temp_holder = tempfile.mkdtemp(prefix="kbsub-")
    try:
        temp_root = Path(temp_holder)
        if source_path.is_file():
            try:
                pack_dir = _extract_tarball(source_path, temp_root)
            except (tarfile.TarError, ValueError) as exc:
                return error("tarball_invalid", str(exc))
        else:
            staged = temp_root / source_path.name
            shutil.copytree(source_path, staged)
            pack_dir = staged

        try:
            manifest = _read_manifest(pack_dir)
        except Exception as exc:
            return error("manifest_invalid", str(exc))

        publisher_id = manifest.get("publisher", {}).get("id")
        if not publisher_id:
            return error("manifest_invalid", "pack.manifest.yaml missing publisher.id")

        # Figure out which key_id the pack was signed with so we can
        # register the right (publisher_id, key_id) pair in TOFU mode.
        from kb_pack import load_attestation
        attestation_path = pack_dir / manifest["attestations"]["provenance"]
        provenance = load_attestation(attestation_path)
        pack_key_id = provenance["signature"]["key_id"]
        pack_pubkey_hex = _bundled_pubkey_hex(pack_dir)

        resolver = resolver_from_trust_store(root)
        existing_key = resolver.lookup(publisher_id, pack_key_id)
        if existing_key is None:
            if not _policy_allows_tofu(root):
                return error(
                    "untrusted_publisher",
                    f"{publisher_id} / {pack_key_id} not in trust store and "
                    "the current policy does not permit TOFU registration.",
                )
            register_publisher_key(
                root,
                publisher_id=publisher_id,
                key_id=pack_key_id,
                public_key_hex=pack_pubkey_hex,
                display_name=display_name if isinstance(display_name, str) else None,
                origin="kb/subscribe/0.1 (TOFU)",
            )
            resolver.register(publisher_id, pack_key_id, pack_pubkey_hex)
        elif existing_key != pack_pubkey_hex:
            return error(
                "key_change_detected",
                "Publisher presented a different key than previously seen; "
                "manual confirm required.",
            )

        result = verify_pack(pack_dir, resolver)
        if not result.ok:
            return error(
                f"verify_failed_{result.step}",
                result.message,
            )

        version = manifest.get("version") or "0.0.0"
        subscription_root = (
            root
            / "subscriptions"
            / did_to_safe_path(publisher_id)
            / manifest["pack_id"]
            / version
        )
        if subscription_root.exists():
            _chmod_tree_writable(subscription_root)
            shutil.rmtree(subscription_root)
        subscription_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pack_dir, subscription_root)
        _chmod_tree_read_only(subscription_root)

        return ok(
            {
                "pack_id": manifest["pack_id"],
                "version": version,
                "publisher_id": publisher_id,
                "content_root": result.content_root,
                "pack_root": result.pack_root,
                "installed_at": str(subscription_root.relative_to(root)),
                "tier_on_subscribe": ctx.tier,
            }
        )
    finally:
        shutil.rmtree(temp_holder, ignore_errors=True)
        if fetched_scratch:
            shutil.rmtree(fetched_scratch, ignore_errors=True)
