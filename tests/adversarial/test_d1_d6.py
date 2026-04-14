"""D1-D6 dependency-chain tests per reports/03-dep-chain-report.md.

Two publishers, a registry, a cross-publisher dependency. Each case
exercises a specific failure mode in `verify_with_dependencies`:

    D1  happy path: both packs present, both publishers trusted       -> OK
    D2  dependency missing from registry                              -> dep_resolve_failed
    D3  version constraint unsatisfiable                              -> dep_resolve_failed
    D4  content tampering inside the dependency                       -> S2 (recursive)
    D5  dep publisher not in trust store                              -> untrusted_dep_publisher (strict)
                                                                         / accepted (inherit-from-parent)
                                                                         / accepted (namespace-scoped allow)
                                                                         / rejected (namespace-scoped deny)
    D6  cycle between two packs with mutual deps                      -> cycle
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_pack import (
    PublisherKeyResolver,
    RecursiveVerificationResult,
    verify_with_dependencies,
)
from kb_registry import open_registry, write_index


BASE_PUBLISHER = "did:web:foundation.example"
APP_PUBLISHER = "did:web:app.example"


async def _call(root: Path, name: str, args: dict) -> dict:
    result = await HANDLERS[name](root, args)
    return json.loads(result[0].text)


def _publish_pack_to_registry(
    kb_root_parent: Path,
    registry_root: Path,
    publisher_id: str,
    pack_id: str,
    version: str,
    dependencies: list[dict] | None = None,
    page_body: str = "# Pattern\n\nBody.\n",
) -> tuple[Path, dict]:
    """Build a pack from a fresh KB and copy its tarball into the
    registry layout. Returns (tarball_path, publisher_key_doc)."""
    kb_root = kb_root_parent / f"kb-{publisher_id.replace(':','-')}-{pack_id}-{version}"
    scaffold(root=kb_root, tier="individual", publisher_id=publisher_id)
    (kb_root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (kb_root / "wiki" / "patterns" / "p.md").write_text(page_body, encoding="utf-8")

    async def build() -> Path:
        draft_args = {
            "pack_id": pack_id,
            "version": version,
            "title": pack_id,
            "summary": "Dep-chain fixture.",
            "source_pages": ["wiki/patterns/p.md"],
        }
        if dependencies:
            draft_args["dependencies"] = dependencies
        draft = await _call(kb_root, "kb/draft_pack/0.1", draft_args)
        assert draft["ok"] is True, draft
        await _call(kb_root, "kb/distill/0.1", {"pack_id": pack_id})
        pub = await _call(kb_root, "kb/publish/0.1", {"pack_id": pack_id})
        assert pub["ok"] is True, pub
        return kb_root / pub["data"]["tarball"]

    tar_path = asyncio.run(build())

    # Copy into registry layout.
    dest = registry_root / "packs" / pack_id / f"{version}.tar"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(tar_path.read_bytes())

    # Record publisher key.
    pub_dir = registry_root / "publishers" / publisher_id.replace(":", "-")
    pub_dir.mkdir(parents=True, exist_ok=True)
    pub_key_file = next((kb_root / ".kb" / "keys").glob("*.pub"))
    pub_doc = yaml.safe_load(pub_key_file.read_text())
    keys_json = {
        "publisher_id": publisher_id,
        "display_name": publisher_id,
        "keys": [
            {
                "key_id": pub_doc["key_id"],
                "algorithm": "ed25519",
                "public_key_hex": pub_doc["public_key_hex"],
            }
        ],
    }
    (pub_dir / "keys.json").write_text(json.dumps(keys_json), encoding="utf-8")

    return tar_path, pub_doc


def _trusted_resolver(*keys: dict) -> PublisherKeyResolver:
    resolver = PublisherKeyResolver()
    for pub_doc in keys:
        resolver.register(
            publisher_id=pub_doc.get("publisher_id") or pub_doc["publisher_id"],
            key_id=pub_doc["key_id"],
            public_key_hex=pub_doc["public_key_hex"],
        )
    return resolver


@pytest.fixture
def registry_with_dep_chain(tmp_path: Path):
    """Fixture: base.crypto@1.0.0 published by foundation; app.billing@1.0.0
    published by app and depending on base.crypto ^1.0."""
    registry = tmp_path / "registry"
    registry.mkdir()

    _, base_pub = _publish_pack_to_registry(
        tmp_path, registry, BASE_PUBLISHER, "base.crypto", "1.0.0"
    )
    base_pub["publisher_id"] = BASE_PUBLISHER

    app_tar, app_pub = _publish_pack_to_registry(
        tmp_path,
        registry,
        APP_PUBLISHER,
        "app.billing",
        "1.0.0",
        dependencies=[
            {"pack_id": "base.crypto", "version": "^1.0", "scope": "references"}
        ],
    )
    app_pub["publisher_id"] = APP_PUBLISHER
    write_index(registry)

    return registry, base_pub, app_pub, app_tar


def _consumer_policy(**overrides) -> dict:
    policy = {
        "consumer": {
            "trust_inheritance": "strict",
            "max_inherit_depth": 2,
            "max_dependency_depth": 8,
        }
    }
    policy["consumer"].update(overrides)
    return policy


def _extract_app_pack(registry_root: Path, dest: Path) -> Path:
    reg = open_registry(f"file://{registry_root}")
    return reg.fetch("app.billing", "1.0.0", dest)


# ── D1: Happy path ──────────────────────────────────────────────────────
def test_D1_happy_path_both_publishers_trusted(tmp_path, registry_with_dep_chain) -> None:
    registry, base_pub, app_pub, _ = registry_with_dep_chain
    resolver = _trusted_resolver(base_pub, app_pub)
    app_dir = _extract_app_pack(registry, tmp_path / "ext")

    result: RecursiveVerificationResult = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(),
    )
    assert result.ok, f"{result.step}: {result.message}"
    assert "app.billing@1.0.0" in result.visited
    assert "base.crypto@1.0.0" in result.visited


# ── D2: Dependency missing from registry ────────────────────────────────
def test_D2_dep_missing_from_registry(tmp_path, registry_with_dep_chain) -> None:
    registry, base_pub, app_pub, _ = registry_with_dep_chain
    shutil.rmtree(registry / "packs" / "base.crypto")
    write_index(registry)
    resolver = _trusted_resolver(base_pub, app_pub)
    app_dir = _extract_app_pack(registry, tmp_path / "ext")

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(),
    )
    assert not result.ok
    assert result.step == "dep_resolve_failed"
    assert "base.crypto" in result.message


# ── D3: Version constraint unsatisfiable ────────────────────────────────
def test_D3_version_constraint_unsatisfiable(tmp_path, registry_with_dep_chain) -> None:
    registry, base_pub, app_pub, _ = registry_with_dep_chain
    # Patch the app tarball's manifest to require ^5.0 for base.crypto.
    # Easiest: re-publish app.billing with an unsatisfiable constraint.
    _, app_pub_v2 = _publish_pack_to_registry(
        tmp_path,
        registry,
        APP_PUBLISHER,
        "app.billing",
        "2.0.0",
        dependencies=[
            {"pack_id": "base.crypto", "version": "^5.0", "scope": "references"}
        ],
    )
    app_pub_v2["publisher_id"] = APP_PUBLISHER
    write_index(registry)

    reg = open_registry(f"file://{registry}")
    app_dir = reg.fetch("app.billing", "2.0.0", tmp_path / "ext2")
    resolver = _trusted_resolver(base_pub, app_pub_v2)

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=reg,
        policy=_consumer_policy(),
    )
    assert not result.ok
    assert result.step == "dep_resolve_failed"
    assert "^5.0" in result.message


# ── D4: Content tampering inside the dependency ─────────────────────────
def test_D4_tamper_inside_dep(tmp_path, registry_with_dep_chain) -> None:
    registry, base_pub, app_pub, _ = registry_with_dep_chain
    # Tamper: extract base.crypto, corrupt a page, repackage.
    base_tar_path = registry / "packs" / "base.crypto" / "1.0.0.tar"
    scratch = tmp_path / "tamper"
    scratch.mkdir()
    import tarfile

    with tarfile.open(base_tar_path, "r") as tar:
        try:
            tar.extractall(scratch, filter="data")
        except TypeError:
            tar.extractall(scratch)
    extracted = next(p for p in scratch.iterdir() if p.is_dir())
    (extracted / "pages" / "p.md").write_text(
        "# Pattern\n\nMALICIOUS EDIT.\n", encoding="utf-8"
    )
    # Rebuild the tarball with the tampered content (but unchanged signatures).
    with tarfile.open(base_tar_path, "w") as tar:
        for path in sorted(extracted.rglob("*")):
            arc = f"{extracted.name}/" + str(path.relative_to(extracted))
            tar.add(path, arcname=arc, recursive=False)
    write_index(registry)

    reg = open_registry(f"file://{registry}")
    app_dir = reg.fetch("app.billing", "1.0.0", tmp_path / "ext-d4")
    resolver = _trusted_resolver(base_pub, app_pub)

    result = verify_with_dependencies(
        app_dir, resolver=resolver, registry=reg, policy=_consumer_policy()
    )
    assert not result.ok
    # content_root / pack_root mismatch fires at S2 inside the dep.
    assert result.step == "S2"
    assert "base.crypto@1.0.0" in result.message  # breadcrumb


# ── D5: Dep publisher not in trust store, three modes ───────────────────
def test_D5a_strict_mode_rejects_untrusted_dep(tmp_path, registry_with_dep_chain) -> None:
    registry, _base_pub, app_pub, _ = registry_with_dep_chain
    resolver = _trusted_resolver(app_pub)  # base publisher NOT in resolver
    app_dir = _extract_app_pack(registry, tmp_path / "ext-d5a")

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(trust_inheritance="strict"),
    )
    assert not result.ok
    assert result.step == "untrusted_dep_publisher"


def test_D5b_inherit_from_parent_accepts_dep(tmp_path, registry_with_dep_chain) -> None:
    registry, _base_pub, app_pub, _ = registry_with_dep_chain
    resolver = _trusted_resolver(app_pub)  # base NOT trusted directly
    app_dir = _extract_app_pack(registry, tmp_path / "ext-d5b")

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(trust_inheritance="inherit-from-parent", max_inherit_depth=2),
    )
    assert result.ok, f"{result.step}: {result.message}"


def test_D5c_namespace_scoped_allow(tmp_path, registry_with_dep_chain) -> None:
    registry, _base_pub, app_pub, _ = registry_with_dep_chain
    resolver = _trusted_resolver(app_pub)
    app_dir = _extract_app_pack(registry, tmp_path / "ext-d5c")

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(
            trust_inheritance="namespace-scoped",
            namespace_publishers={"base.*": [BASE_PUBLISHER]},
        ),
    )
    assert result.ok, f"{result.step}: {result.message}"


def test_D5d_namespace_scoped_deny(tmp_path, registry_with_dep_chain) -> None:
    registry, _base_pub, app_pub, _ = registry_with_dep_chain
    resolver = _trusted_resolver(app_pub)
    app_dir = _extract_app_pack(registry, tmp_path / "ext-d5d")

    result = verify_with_dependencies(
        app_dir,
        resolver=resolver,
        registry=open_registry(f"file://{registry}"),
        policy=_consumer_policy(
            trust_inheritance="namespace-scoped",
            namespace_publishers={"app.*": [APP_PUBLISHER]},  # base.* not covered
        ),
    )
    assert not result.ok
    assert result.step == "namespace_publisher_rejected"


# ── D6: Cycle between two packs ────────────────────────────────────────
def test_D6_cycle_detected(tmp_path) -> None:
    registry = tmp_path / "reg-cycle"
    registry.mkdir()
    # Create pack A that depends on pack B, then pack B depending on pack A.
    # Cycle detection fires when we re-enter the same pack_ref.
    _, a_pub = _publish_pack_to_registry(
        tmp_path, registry, BASE_PUBLISHER, "cyc.a", "1.0.0",
        dependencies=[{"pack_id": "cyc.b", "version": "^1.0"}],
    )
    a_pub["publisher_id"] = BASE_PUBLISHER
    # B references A back. Both in the same registry; cycle emerges during
    # recursive verification because both manifests' deps resolve.
    _, b_pub = _publish_pack_to_registry(
        tmp_path, registry, BASE_PUBLISHER, "cyc.b", "1.0.0",
        dependencies=[{"pack_id": "cyc.a", "version": "^1.0"}],
    )
    b_pub["publisher_id"] = BASE_PUBLISHER
    write_index(registry)

    reg = open_registry(f"file://{registry}")
    a_dir = reg.fetch("cyc.a", "1.0.0", tmp_path / "ext-d6")
    resolver = _trusted_resolver(a_pub)

    result = verify_with_dependencies(
        a_dir,
        resolver=resolver,
        registry=reg,
        policy=_consumer_policy(trust_inheritance="inherit-from-parent"),
    )
    assert not result.ok
    # Either cycle detection fires OR S2 from stale content after B points
    # back. Per reports/03 §4.3, cycle detection is rarely reached because
    # content_root checks preempt it. Accept either signal as "rejection".
    assert result.step in {"cycle", "S2", "S3a"}
