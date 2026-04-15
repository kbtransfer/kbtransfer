"""RFC-0002 library-level tests: RegistryServer.submit() + validate_submission_bytes."""

from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_registry import write_index
from kb_registry_server import (
    CHECK_NAMES,
    RegistryServer,
    ServerConfig,
    SubmissionResult,
    ValidationError,
    validate_submission_bytes,
)


def _build_pack(tmp_path: Path, pack_id: str, version: str, publisher_id: str) -> Path:
    kb_root = tmp_path / f"pub-{pack_id}-{version}"
    scaffold(root=kb_root, tier="individual", publisher_id=publisher_id)
    (kb_root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (kb_root / "wiki" / "patterns" / "p.md").write_text(
        f"# {pack_id}\n\nBody.\n", encoding="utf-8"
    )

    async def run() -> Path:
        async def call(name: str, args: dict) -> dict:
            result = await HANDLERS[name](kb_root, args)
            return json.loads(result[0].text)

        draft = await call(
            "kb/draft_pack/0.1",
            {
                "pack_id": pack_id,
                "version": version,
                "title": pack_id,
                "summary": "RFC-0002 submit fixture.",
                "source_pages": ["wiki/patterns/p.md"],
            },
        )
        assert draft["ok"], draft
        await call("kb/distill/0.1", {"pack_id": pack_id})
        published = await call("kb/publish/0.1", {"pack_id": pack_id})
        assert published["ok"], published
        return kb_root / published["data"]["tarball"]

    return asyncio.run(run())


def _install_publisher_keys(
    registry_root: Path, publisher_id: str, kb_root: Path
) -> Path:
    did_safe = publisher_id.replace(":", "-").replace("/", "-")
    pub_dir = registry_root / "publishers" / did_safe
    pub_dir.mkdir(parents=True, exist_ok=True)
    pub_key_file = next((kb_root / ".kb" / "keys").glob("*.pub"))
    pub_doc = yaml.safe_load(pub_key_file.read_text())
    keys_json = {
        "publisher_id": publisher_id,
        "display_name": "Test",
        "keys": [
            {
                "key_id": pub_doc["key_id"],
                "algorithm": "ed25519",
                "public_key_hex": pub_doc["public_key_hex"],
            }
        ],
    }
    keys_file = pub_dir / "keys.json"
    keys_file.write_text(json.dumps(keys_json), encoding="utf-8")
    return keys_file


@pytest.fixture
def empty_registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    (root / "packs").mkdir(parents=True)
    (root / "publishers").mkdir(parents=True)
    write_index(root)
    return root


@pytest.fixture
def signed_tarball(tmp_path: Path, empty_registry: Path) -> tuple[bytes, Path]:
    publisher_id = "did:web:alice.example"
    tar_path = _build_pack(tmp_path, "demo.rfc0002", "1.0.0", publisher_id)
    kb_root = tar_path.parents[1]  # <kb>/published/<file>.tar
    _install_publisher_keys(empty_registry, publisher_id, kb_root)
    return tar_path.read_bytes(), tar_path


def test_check_names_are_a_stable_ordered_tuple() -> None:
    assert isinstance(CHECK_NAMES, tuple)
    assert "signature_verify" in CHECK_NAMES
    assert "version_uniqueness" in CHECK_NAMES
    assert "publisher_keys_known" in CHECK_NAMES


def test_validate_accepts_a_freshly_published_pack(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _tar_path = signed_tarball
    result = validate_submission_bytes(tar_bytes, empty_registry)
    assert result.pack_id == "demo.rfc0002"
    assert result.version == "1.0.0"
    assert result.publisher_id == "did:web:alice.example"
    assert result.size_bytes == len(tar_bytes)
    assert result.checks_passed == list(CHECK_NAMES)


def test_validate_rejects_oversize_tarball(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    with pytest.raises(ValidationError) as exc_info:
        validate_submission_bytes(tar_bytes, empty_registry, max_bytes=100)
    assert exc_info.value.check == "size_limit"


def test_validate_rejects_unknown_publisher(
    tmp_path: Path, empty_registry: Path
) -> None:
    # Build a pack but do NOT install the publisher keys.
    publisher_id = "did:web:stranger.example"
    tar_path = _build_pack(tmp_path, "stranger.pack", "1.0.0", publisher_id)
    with pytest.raises(ValidationError) as exc_info:
        validate_submission_bytes(tar_path.read_bytes(), empty_registry)
    assert exc_info.value.check == "publisher_keys_known"


def test_validate_rejects_consortium_non_allowlisted_publisher(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    with pytest.raises(ValidationError) as exc_info:
        validate_submission_bytes(
            tar_bytes,
            empty_registry,
            trust_role="consortium",
            allowlist=("did:web:someone-else.example",),
        )
    assert exc_info.value.check == "publisher_admitted"


def test_validate_rejects_duplicate_version(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    # Pre-place the tarball in the layout so uniqueness fires.
    target = empty_registry / "packs" / "demo.rfc0002" / "1.0.0.tar"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(tar_bytes)
    with pytest.raises(ValidationError) as exc_info:
        validate_submission_bytes(tar_bytes, empty_registry)
    assert exc_info.value.check == "version_uniqueness"


def test_validate_rejects_tampered_signature(
    tmp_path: Path, empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    _tar_bytes, tar_path = signed_tarball
    # Unpack, append bytes to one wiki page so content_root no longer matches
    # the signed pack.lock, and repack. This breaks S2 before S5 can fire.
    scratch = tmp_path / "unpack"
    scratch.mkdir()
    with tarfile.open(tar_path, "r") as tar:
        try:
            tar.extractall(scratch, filter="data")
        except TypeError:
            tar.extractall(scratch)
    inner = next(p for p in scratch.iterdir() if p.is_dir())
    pages = inner / "pages"
    first_page = next(pages.glob("*.md"))
    first_page.write_text(first_page.read_text() + "\nTAMPERED\n", encoding="utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(inner.rglob("*")):
            arc = inner.name + "/" + str(path.relative_to(inner))
            tar.add(path, arcname=arc, recursive=False)
    with pytest.raises(ValidationError) as exc_info:
        validate_submission_bytes(buf.getvalue(), empty_registry)
    # Either content_root_recompute or signature_verify; both map to
    # "the pack has been mutated after signing", which is exactly the
    # intent of this test.
    assert exc_info.value.check in {
        "content_root_recompute",
        "signature_verify",
    }


def test_registry_server_submit_commits_auto_mode(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    server = RegistryServer(ServerConfig(registry_root=empty_registry))
    result = server.submit(tar_bytes)
    assert result.accepted, result.errors
    assert result.canonical_path == "packs/demo.rfc0002/1.0.0.tar"
    assert (empty_registry / result.canonical_path).is_file()
    # Index rebuilt after commit.
    index = json.loads((empty_registry / "index.json").read_text())
    assert "demo.rfc0002" in index["packs"]


def test_registry_server_submit_stages_in_stage_mode(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    server = RegistryServer(
        ServerConfig(registry_root=empty_registry, commit_mode="stage")
    )
    result = server.submit(tar_bytes)
    assert result.accepted
    assert result.commit_mode == "stage"
    assert result.canonical_path.startswith("submissions/")
    # Pending file exists, packs/ still empty.
    assert (empty_registry / result.canonical_path).is_file()
    assert not (empty_registry / "packs" / "demo.rfc0002" / "1.0.0.tar").exists()


def test_registry_server_submit_returns_structured_error(
    tmp_path: Path, empty_registry: Path
) -> None:
    publisher_id = "did:web:unknown.example"
    tar_path = _build_pack(tmp_path, "ghost.pack", "1.0.0", publisher_id)
    server = RegistryServer(ServerConfig(registry_root=empty_registry))
    result = server.submit(tar_path.read_bytes())
    assert not result.accepted
    assert result.errors
    assert result.errors[0]["check"] == "publisher_keys_known"
    # Tree untouched — nothing written on rejection.
    assert not any((empty_registry / "packs").rglob("*.tar"))
    assert not (empty_registry / "submissions").exists()


def test_private_tier_requires_bearer_token(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    tar_bytes, _ = signed_tarball
    server = RegistryServer(
        ServerConfig(
            registry_root=empty_registry,
            trust_role="private",
            bearer_tokens=frozenset({"s3cret"}),
        )
    )
    missing = server.submit(tar_bytes)
    assert not missing.accepted
    assert missing.errors[0]["check"] == "bearer_token"

    wrong = server.submit(tar_bytes, bearer_token="not-the-token")
    assert not wrong.accepted
    assert wrong.errors[0]["check"] == "bearer_token"

    ok_result = server.submit(tar_bytes, bearer_token="s3cret")
    assert ok_result.accepted


def test_server_config_rejects_invalid_role() -> None:
    with pytest.raises(ValueError):
        ServerConfig(registry_root=Path("/tmp"), trust_role="bogus")


def test_server_config_rejects_invalid_commit_mode() -> None:
    with pytest.raises(ValueError):
        ServerConfig(registry_root=Path("/tmp"), commit_mode="schedule")


def test_private_tier_without_tokens_is_misconfig() -> None:
    with pytest.raises(ValueError, match="bearer token"):
        ServerConfig(registry_root=Path("/tmp"), trust_role="private")


def test_submission_result_wire_shape(
    empty_registry: Path, signed_tarball: tuple[bytes, Path]
) -> None:
    server = RegistryServer(ServerConfig(registry_root=empty_registry))
    accepted = server.submit(signed_tarball[0])
    wire = accepted.to_wire()
    assert wire["accepted"] is True
    assert wire["pack_id"] == "demo.rfc0002"
    assert wire["checks_passed"] == list(CHECK_NAMES)
    assert "errors" not in wire
