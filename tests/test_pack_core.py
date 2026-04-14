"""Tests for kb_pack core: canonical JSON, manifest, merkle, lock."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kb_pack import (
    ManifestError,
    build_lock_for,
    canonical_json,
    compute_roots,
    load_manifest,
    parse_lock,
    render_lock,
    write_lock,
)


def test_canonical_json_sorts_keys_and_strips_whitespace() -> None:
    raw = {"b": 2, "a": {"y": 1, "x": 0}}
    assert canonical_json(raw) == b'{"a":{"x":0,"y":1},"b":2}'


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_canonical_json_utf8_preserves_unicode_directly() -> None:
    assert canonical_json({"k": "pé"}) == b'{"k":"p\xc3\xa9"}'


def _write_minimum_pack(root: Path) -> None:
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "attestations").mkdir(parents=True, exist_ok=True)
    (root / "signatures").mkdir(parents=True, exist_ok=True)

    manifest_doc = {
        "spec_version": "autoevolve-pack/0.1.1",
        "pack_id": "example.minimal",
        "version": "1.0.0",
        "namespace": "example",
        "publisher": {"id": "did:web:example.invalid", "display_name": "Ex"},
        "title": "Minimum Viable Pack",
        "page_count": 1,
        "total_size_bytes": 0,
        "attestations": {
            "provenance": "attestations/provenance.json",
            "redaction": "attestations/redaction.json",
            "evaluation": "attestations/evaluation.json",
            "license": "attestations/license.json",
        },
        "policy_surface": ["redaction_level", "license_class"],
    }
    (root / "pack.manifest.yaml").write_text(
        yaml.safe_dump(manifest_doc, sort_keys=False), encoding="utf-8"
    )
    (root / "README.md").write_text("# Hello\n", encoding="utf-8")
    (root / "pages" / "pattern.md").write_text("# Pattern\n\nBody.\n", encoding="utf-8")
    for kind in ("provenance", "redaction", "evaluation", "license"):
        (root / "attestations" / f"{kind}.json").write_text("{}", encoding="utf-8")


def test_load_manifest_returns_typed_wrapper(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    manifest = load_manifest(tmp_path)
    assert manifest.pack_id == "example.minimal"
    assert manifest.version == "1.0.0"
    assert manifest.publisher_id == "did:web:example.invalid"
    assert manifest.pack_ref == "example.minimal@1.0.0"


def test_manifest_rejects_lock_hash(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    manifest_path = tmp_path / "pack.manifest.yaml"
    doc = yaml.safe_load(manifest_path.read_text())
    doc["lock_hash"] = "sha256:feedface"
    manifest_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ManifestError, match="A2"):
        load_manifest(tmp_path)


def test_manifest_rejects_missing_attestations(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    manifest_path = tmp_path / "pack.manifest.yaml"
    doc = yaml.safe_load(manifest_path.read_text())
    doc["attestations"].pop("license")
    manifest_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ManifestError, match="license"):
        load_manifest(tmp_path)


def test_compute_roots_excludes_lock_and_signatures(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    (tmp_path / "pack.lock").write_text("stale; should be excluded", encoding="utf-8")
    (tmp_path / "signatures" / "publisher.sig").write_bytes(b"\x00" * 64)
    content_root, pack_root, entries = compute_roots(tmp_path)
    paths = {e.relative_path for e in entries}
    assert "pack.lock" not in paths
    assert all(not p.startswith("signatures/") for p in paths)
    assert content_root != pack_root


def test_content_root_is_independent_of_attestation_changes(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    c1, _, _ = compute_roots(tmp_path)
    (tmp_path / "attestations" / "redaction.json").write_text(
        '{"later": "edit"}', encoding="utf-8"
    )
    c2, _, _ = compute_roots(tmp_path)
    assert c1 == c2


def test_pack_root_changes_when_attestations_change(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    _, p1, _ = compute_roots(tmp_path)
    (tmp_path / "attestations" / "redaction.json").write_text(
        '{"later": "edit"}', encoding="utf-8"
    )
    _, p2, _ = compute_roots(tmp_path)
    assert p1 != p2


def test_lock_round_trips_through_render_and_parse(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    lock = build_lock_for(tmp_path)
    rendered = render_lock(lock)
    parsed = parse_lock(rendered)
    assert parsed.entries == lock.entries
    assert parsed.content_root == lock.content_root
    assert parsed.pack_root == lock.pack_root


def test_write_lock_produces_file_with_expected_headers(tmp_path: Path) -> None:
    _write_minimum_pack(tmp_path)
    lock = build_lock_for(tmp_path)
    write_lock(tmp_path, lock)
    text = (tmp_path / "pack.lock").read_text(encoding="utf-8")
    assert text.startswith("# pack.lock\n# autoevolve-pack/0.1.1\n")
    assert "content_root: sha256:" in text
    assert "pack_root:    sha256:" in text
