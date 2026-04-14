"""Recursive dependency verification with trust-inheritance policy.

Extends the single-pack verifier from `verify.py` with the spec's
§6 step 6 resolution path. A consumer hands the entry point a
registry, their trust-store-backed resolver, and a policy document;
for each dependency listed in the root manifest we:

1. Resolve the constraint against the registry (defaulting the
   supplied registry unless the dep carries a `registry_hint`).
2. Fetch the pack tarball, extract it, and recursively verify.
3. Apply the trust-inheritance policy when a dep's publisher is not
   yet in the consumer's resolver:

       strict              — reject (v0.1.1 behavior, still the
                             default for enterprise tier).
       inherit-from-parent — auto-trust the dep's publisher up to
                             max_inherit_depth levels deep, using
                             the key bundled inside the dep's pack.
       namespace-scoped    — trust only if the dep's pack_id falls
                             under a namespace glob in
                             `consumer.namespace_publishers` AND
                             the dep's publisher is in the allowed
                             list for that namespace.

Every failure carries a breadcrumb list so deep chains produce
readable messages: `qr-offline@1.0.1 -> base.crypto@1.0.0 -> ...`.
"""

from __future__ import annotations

import fnmatch
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kb_pack.manifest import load_manifest
from kb_pack.verify import PublisherKeyResolver, VerificationResult, verify_pack
from kb_registry import Registry, RegistryError, open_registry

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_INHERIT_DEPTH = 2


@dataclass
class DependencyResult:
    pack_ref: str
    result: VerificationResult


@dataclass
class RecursiveVerificationResult:
    ok: bool
    step: str
    message: str
    breadcrumb: list[str] = field(default_factory=list)
    visited: dict[str, VerificationResult] = field(default_factory=dict)

    def breadcrumb_text(self) -> str:
        return " -> ".join(self.breadcrumb) if self.breadcrumb else "(root)"


def _fail(
    step: str,
    message: str,
    breadcrumb: list[str],
    visited: dict[str, VerificationResult],
) -> RecursiveVerificationResult:
    return RecursiveVerificationResult(
        ok=False,
        step=step,
        message=f"{message} [{' -> '.join(breadcrumb) if breadcrumb else 'root'}]",
        breadcrumb=list(breadcrumb),
        visited=visited,
    )


def _trust_inheritance_config(policy: dict[str, Any]) -> dict[str, Any]:
    consumer = policy.get("consumer", {}) if isinstance(policy, dict) else {}
    mode = consumer.get("trust_inheritance", "strict")
    if not isinstance(mode, str):
        mode = "strict"
    return {
        "mode": mode,
        "max_inherit_depth": int(
            consumer.get("max_inherit_depth", DEFAULT_MAX_INHERIT_DEPTH)
        ),
        "namespace_publishers": consumer.get("namespace_publishers") or {},
        "max_dependency_depth": int(
            consumer.get("max_dependency_depth", DEFAULT_MAX_DEPTH)
        ),
    }


def _bundled_key(pack_dir: Path) -> tuple[str, str] | None:
    """Returns (key_id, public_key_hex) from the pack's bundled
    signature files, if present. The signature file's key_id is
    recovered from the first attestation (all four share the same
    key_id by construction)."""
    pub_path = pack_dir / "signatures" / "publisher.pubkey"
    if not pub_path.is_file():
        return None
    hexkey = pub_path.read_bytes().hex()
    import json

    for kind in ("provenance", "redaction", "evaluation", "license"):
        att_path = pack_dir / "attestations" / f"{kind}.json"
        if att_path.is_file():
            try:
                data = json.loads(att_path.read_text(encoding="utf-8"))
                envelope = data.get("signature", {})
                key_id = envelope.get("key_id")
                if key_id:
                    return key_id, hexkey
            except Exception:
                continue
    return None


def _namespace_allows(
    namespace_publishers: dict[str, Any],
    pack_id: str,
    publisher_id: str,
) -> bool:
    for pattern, allowed in namespace_publishers.items():
        if not isinstance(allowed, list):
            continue
        if fnmatch.fnmatch(pack_id, pattern):
            if publisher_id in allowed:
                return True
    return False


def _apply_inheritance(
    resolver: PublisherKeyResolver,
    dep_pack_dir: Path,
    dep_manifest_publisher: str,
    inherit_config: dict[str, Any],
    inherit_depth: int,
    pack_id: str,
    breadcrumb: list[str],
    visited: dict[str, VerificationResult],
) -> RecursiveVerificationResult | None:
    """Extend `resolver` with the dep's publisher key if the current
    inheritance policy allows it. Returns None on success, a failure
    result on rejection, and None when the publisher was already
    trusted (nothing to do)."""
    bundled = _bundled_key(dep_pack_dir)
    if bundled is None:
        return _fail(
            "dep_missing_pubkey",
            "Dependency pack has no bundled publisher.pubkey",
            breadcrumb,
            visited,
        )
    key_id, hexkey = bundled

    if resolver.lookup(dep_manifest_publisher, key_id) is not None:
        return None

    mode = inherit_config["mode"]
    if mode == "strict":
        return _fail(
            "untrusted_dep_publisher",
            f"Publisher {dep_manifest_publisher!r} not in trust store "
            f"and trust_inheritance=strict",
            breadcrumb,
            visited,
        )
    if mode == "inherit-from-parent":
        if inherit_depth >= inherit_config["max_inherit_depth"]:
            return _fail(
                "inherit_depth_exceeded",
                f"max_inherit_depth={inherit_config['max_inherit_depth']} exceeded",
                breadcrumb,
                visited,
            )
        resolver.register(dep_manifest_publisher, key_id, hexkey)
        return None
    if mode == "namespace-scoped":
        if not _namespace_allows(
            inherit_config["namespace_publishers"],
            pack_id,
            dep_manifest_publisher,
        ):
            return _fail(
                "namespace_publisher_rejected",
                f"{dep_manifest_publisher!r} not allowed under namespace rules for {pack_id!r}",
                breadcrumb,
                visited,
            )
        resolver.register(dep_manifest_publisher, key_id, hexkey)
        return None
    return _fail(
        "unknown_trust_inheritance_mode",
        f"Unknown trust_inheritance mode {mode!r}",
        breadcrumb,
        visited,
    )


def _resolve_dep_registry(
    dep: dict[str, Any],
    default_registry: Registry | None,
) -> Registry:
    hint = dep.get("registry_hint")
    if isinstance(hint, str) and hint:
        return open_registry(hint)
    if default_registry is None:
        raise RegistryError(
            "dep has no registry_hint and no default registry was provided"
        )
    return default_registry


def _peek_manifest_publisher(pack_dir: Path) -> str:
    manifest = load_manifest(pack_dir)
    return manifest.publisher_id


def verify_with_dependencies(
    pack_dir: Path,
    resolver: PublisherKeyResolver,
    registry: Registry | None,
    policy: dict[str, Any],
    *,
    breadcrumb: list[str] | None = None,
    visited: dict[str, VerificationResult] | None = None,
    depth: int = 0,
    inherit_depth: int = 0,
) -> RecursiveVerificationResult:
    breadcrumb = list(breadcrumb or [])
    visited = visited if visited is not None else {}
    inherit_config = _trust_inheritance_config(policy)

    if depth > inherit_config["max_dependency_depth"]:
        return _fail(
            "max_dependency_depth",
            f"exceeded max_dependency_depth={inherit_config['max_dependency_depth']}",
            breadcrumb,
            visited,
        )

    # S1-S5 for this pack.
    single = verify_pack(pack_dir, resolver)
    try:
        manifest = load_manifest(pack_dir)
    except Exception as exc:
        return _fail("manifest_invalid", str(exc), breadcrumb, visited)

    pack_ref = manifest.pack_ref
    breadcrumb = breadcrumb + [pack_ref]

    if not single.ok:
        return _fail(single.step, single.message, breadcrumb, visited)

    if pack_ref in visited:
        return _fail(
            "cycle",
            f"dependency cycle detected at {pack_ref}",
            breadcrumb,
            visited,
        )
    visited[pack_ref] = single

    deps = manifest.doc.get("dependencies") or []
    if not isinstance(deps, list):
        return _fail(
            "dependencies_malformed",
            "manifest 'dependencies' must be a list",
            breadcrumb,
            visited,
        )

    for dep in deps:
        if not isinstance(dep, dict):
            return _fail(
                "dep_malformed", "dependency entry must be a mapping",
                breadcrumb, visited,
            )
        dep_pack_id = dep.get("pack_id")
        dep_version = dep.get("version", "*")
        if not isinstance(dep_pack_id, str) or not dep_pack_id:
            return _fail(
                "dep_missing_pack_id",
                "dependency entry missing pack_id",
                breadcrumb, visited,
            )

        try:
            dep_registry = _resolve_dep_registry(dep, registry)
            resolved = dep_registry.resolve(dep_pack_id, dep_version)
        except RegistryError as exc:
            return _fail(
                "dep_resolve_failed",
                f"{dep_pack_id}@{dep_version}: {exc}",
                breadcrumb, visited,
            )

        dep_scratch = Path(tempfile.mkdtemp(prefix="kbsub-deps-"))
        try:
            dep_dir = dep_registry.fetch(
                resolved.pack_id, resolved.version, dep_scratch
            )

            try:
                dep_publisher = _peek_manifest_publisher(dep_dir)
            except Exception as exc:
                return _fail(
                    "dep_manifest_invalid",
                    f"{dep_pack_id}@{resolved.version}: {exc}",
                    breadcrumb, visited,
                )

            inheritance_failure = _apply_inheritance(
                resolver=resolver,
                dep_pack_dir=dep_dir,
                dep_manifest_publisher=dep_publisher,
                inherit_config=inherit_config,
                inherit_depth=inherit_depth,
                pack_id=resolved.pack_id,
                breadcrumb=breadcrumb,
                visited=visited,
            )
            if inheritance_failure is not None:
                return inheritance_failure

            child = verify_with_dependencies(
                dep_dir,
                resolver=resolver,
                registry=registry,
                policy=policy,
                breadcrumb=breadcrumb,
                visited=visited,
                depth=depth + 1,
                inherit_depth=(
                    inherit_depth + 1 if inherit_config["mode"] == "inherit-from-parent" else inherit_depth
                ),
            )
            if not child.ok:
                return child
        finally:
            shutil.rmtree(dep_scratch, ignore_errors=True)

    return RecursiveVerificationResult(
        ok=True,
        step="S7",
        message="verified",
        breadcrumb=breadcrumb,
        visited=visited,
    )
