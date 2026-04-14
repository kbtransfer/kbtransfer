"""T1-T8 adversarial tests per spec v0.1.1 dogfood report (reports/02).

Each test builds a legitimate signed pack, applies a specific attack,
and asserts that verification fails at the expected step. Step
assignments are recorded below; they occasionally differ from the
spec's "expected" step because a lower-numbered check (content hash,
pack_root) fires first — this is the defense-in-depth layering
documented in reports/02-v0.1.1-dogfood-report.md.

    T1  tamper page content                       -> S2
    T2  tamper attestation body                   -> S2
    T3  swap attestation claiming different content -> S2
    T4  manifest.license != license.json          -> S2 (manifest hash changes first)
    T5  empty residual_risk_notes                 -> S2 (file hash changes first)
    T6  invalid key_id in envelope                -> S3b (new content keeps hash, bad key_id)
    T7  algorithm downgrade                       -> S3b
    T8  key compromise + stale attestation reuse  -> S3a (A1 content_root binding)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from kb_cli.keygen import generate_keypair
from kb_pack import (
    PublisherKeyResolver,
    build_evaluation,
    build_license,
    build_pack,
    build_provenance,
    build_redaction,
    canonical_json,
    read_lock,
    sign_attestation,
    sign_pack_root,
    verify_pack,
)

PACK_ID = "advers.pack"
VERSION = "1.0.0"
PUBLISHER = "did:web:adversary.example"


def _manifest_doc() -> dict:
    return {
        "spec_version": "autoevolve-pack/0.1.1",
        "pack_id": PACK_ID,
        "version": VERSION,
        "namespace": "advers",
        "publisher": {"id": PUBLISHER},
        "title": "Adversarial fixture",
        "summary": "Minimum pack for hammering the verifier.",
        "page_count": 1,
        "total_size_bytes": 0,
        "license": {"spdx": "Apache-2.0"},
        "attestations": {
            "provenance": "attestations/provenance.json",
            "redaction": "attestations/redaction.json",
            "evaluation": "attestations/evaluation.json",
            "license": "attestations/license.json",
        },
        "policy_surface": ["redaction_level", "license_class"],
    }


def _write_stubs(pack_dir: Path) -> None:
    (pack_dir / "pages").mkdir(parents=True, exist_ok=True)
    (pack_dir / "attestations").mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.manifest.yaml").write_text(
        yaml.safe_dump(_manifest_doc(), sort_keys=False), encoding="utf-8"
    )
    (pack_dir / "README.md").write_text("# Adversarial\n", encoding="utf-8")
    (pack_dir / "pages" / "pattern.md").write_text(
        "# Pattern\n\nOriginal content.\n", encoding="utf-8"
    )

    pack_ref = f"{PACK_ID}@{VERSION}"
    for kind, builder in (
        ("provenance", lambda: build_provenance(pack_ref, "sha256:x", PUBLISHER, 1, ["x"])),
        (
            "redaction",
            lambda: build_redaction(
                pack_ref,
                "sha256:x",
                PUBLISHER,
                "minimal",
                "test-policy",
                "1.0.0",
                ["None."],
            ),
        ),
        ("evaluation", lambda: build_evaluation(pack_ref, "sha256:x", PUBLISHER, composite_score=0.5)),
        (
            "license",
            lambda: build_license(
                pack_ref, "sha256:x", PUBLISHER, "Apache-2.0", "permissive"
            ),
        ),
    ):
        (pack_dir / "attestations" / f"{kind}.json").write_text(
            json.dumps(builder()), encoding="utf-8"
        )


@pytest.fixture
def signed(tmp_path: Path):
    pack_dir = tmp_path / "pack"
    _write_stubs(pack_dir)
    keypair = generate_keypair(publisher_id=PUBLISHER)
    build_pack(
        pack_dir,
        key_id=keypair.key_id,
        private_key_hex=keypair.private_key_hex,
        public_key_hex=keypair.public_key_hex,
    )
    resolver = PublisherKeyResolver()
    resolver.register(PUBLISHER, keypair.key_id, keypair.public_key_hex)
    return pack_dir, resolver, keypair


def test_T1_tamper_page_content(signed) -> None:
    pack_dir, resolver, _ = signed
    page = pack_dir / "pages" / "pattern.md"
    page.write_text("# Pattern\n\nMALICIOUS INSERTION.\n", encoding="utf-8")
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S2"


def test_T2_tamper_attestation_body(signed) -> None:
    pack_dir, resolver, _ = signed
    att = pack_dir / "attestations" / "evaluation.json"
    data = json.loads(att.read_text())
    data["composite_score"] = 99.9
    att.write_text(canonical_json(data).decode("utf-8"), encoding="utf-8")
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S2"


def test_T3_swap_attestation_with_different_content_root(signed) -> None:
    pack_dir, resolver, _ = signed
    att = pack_dir / "attestations" / "redaction.json"
    data = json.loads(att.read_text())
    data["content_root"] = (
        "sha256:00000000000000000000000000000000000000000000000000000000deadbeef"
    )
    att.write_bytes(canonical_json(data))
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S2"


def test_T4_manifest_license_mismatch_with_license_attestation(signed) -> None:
    pack_dir, resolver, _ = signed
    manifest_path = pack_dir / "pack.manifest.yaml"
    doc = yaml.safe_load(manifest_path.read_text())
    doc["license"]["spdx"] = "MIT"
    manifest_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S2"  # manifest hash changes before B5 check


def test_T5_empty_residual_risk_notes(signed) -> None:
    pack_dir, resolver, _ = signed
    att = pack_dir / "attestations" / "redaction.json"
    data = json.loads(att.read_text())
    data["residual_risk_notes"] = []
    att.write_bytes(canonical_json(data))
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S2"


def test_T6_invalid_key_id_in_envelope(signed, tmp_path: Path) -> None:
    """T6 only becomes interesting when the attacker controls pack.lock
    + publisher signature too; here we simulate that whole-signed state
    by re-running build_pack with a modified attestation containing a
    bogus envelope."""
    pack_dir, _resolver, keypair = signed

    att_path = pack_dir / "attestations" / "provenance.json"
    data = json.loads(att_path.read_text())
    data["signature"] = {
        "algorithm": "ed25519",
        "key_id": "rogue-key-id-does-not-exist",
        "value": data["signature"]["value"],
    }
    att_path.write_bytes(canonical_json(data))
    # Re-run build to refresh pack.lock + publisher signature so the
    # verifier gets past S2 and exercises S3b on this specific
    # attestation. We intentionally keep the legitimate keypair for
    # publishing; only the envelope inside provenance.json claims a
    # non-existent key_id.
    lock = read_lock(pack_dir)  # regenerate later
    # Simulate: the attacker re-signs pack_root with their legit key
    # but leaves the rogue key_id in the attestation envelope intact.
    from kb_pack.lock import build_lock_for, write_lock

    new_lock = build_lock_for(pack_dir)
    write_lock(pack_dir, new_lock)
    sig_bytes = sign_pack_root(new_lock.pack_root.removeprefix("sha256:"), keypair.private_key_hex)
    (pack_dir / "signatures" / "publisher.sig").write_bytes(sig_bytes)

    resolver = PublisherKeyResolver()
    resolver.register(PUBLISHER, keypair.key_id, keypair.public_key_hex)
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S3b"
    assert "untrusted issuer/key_id" in result.message


def test_T7_algorithm_downgrade(signed, tmp_path: Path) -> None:
    pack_dir, _resolver, keypair = signed
    att_path = pack_dir / "attestations" / "redaction.json"
    data = json.loads(att_path.read_text())
    data["signature"] = {
        "algorithm": "rsa",
        "key_id": keypair.key_id,
        "value": data["signature"]["value"],
    }
    att_path.write_bytes(canonical_json(data))
    from kb_pack.lock import build_lock_for, write_lock

    new_lock = build_lock_for(pack_dir)
    write_lock(pack_dir, new_lock)
    sig_bytes = sign_pack_root(new_lock.pack_root.removeprefix("sha256:"), keypair.private_key_hex)
    (pack_dir / "signatures" / "publisher.sig").write_bytes(sig_bytes)

    resolver = PublisherKeyResolver()
    resolver.register(PUBLISHER, keypair.key_id, keypair.public_key_hex)
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S3b"


def test_T8_key_compromise_stale_attestation_reuse(tmp_path: Path) -> None:
    """The canonical A1 test. Attacker has the publisher's key. They take
    a legitimate attestation from pack-v1, drop it onto pack-v2 which
    has DIFFERENT malicious content, and re-sign pack_root with the
    stolen key. Without A1 (content_root binding), the attestation
    would verify; with A1, verification fails at S3a because the
    reused attestation's content_root does not match pack-v2's."""
    # --- Publish pack v1 legitimately ---
    keypair = generate_keypair(publisher_id=PUBLISHER)
    v1_dir = tmp_path / "pack-v1"
    _write_stubs(v1_dir)
    build_pack(
        v1_dir,
        key_id=keypair.key_id,
        private_key_hex=keypair.private_key_hex,
        public_key_hex=keypair.public_key_hex,
    )
    legitimate_redaction = json.loads(
        (v1_dir / "attestations" / "redaction.json").read_text()
    )

    # --- Attacker has the key + wants to ship malicious content v2 ---
    v2_dir = tmp_path / "pack-v2"
    _write_stubs(v2_dir)
    (v2_dir / "pages" / "pattern.md").write_text(
        "# Pattern\n\nMALICIOUS content replaces the original.\n", encoding="utf-8"
    )

    # Build v2 normally (so all four attestations are fresh).
    build_pack(
        v2_dir,
        key_id=keypair.key_id,
        private_key_hex=keypair.private_key_hex,
        public_key_hex=keypair.public_key_hex,
    )

    # Replace v2's redaction attestation with the *old* one from v1,
    # preserving the attacker's signing key but carrying v1's content_root.
    (v2_dir / "attestations" / "redaction.json").write_bytes(
        canonical_json(legitimate_redaction)
    )
    # Re-lock + re-sign pack_root so S2 passes.
    from kb_pack.lock import build_lock_for, write_lock

    new_lock = build_lock_for(v2_dir)
    write_lock(v2_dir, new_lock)
    sig_bytes = sign_pack_root(
        new_lock.pack_root.removeprefix("sha256:"), keypair.private_key_hex
    )
    (v2_dir / "signatures" / "publisher.sig").write_bytes(sig_bytes)

    resolver = PublisherKeyResolver()
    resolver.register(PUBLISHER, keypair.key_id, keypair.public_key_hex)

    result = verify_pack(v2_dir, resolver)
    assert not result.ok, "T8 should not be silently accepted"
    assert result.step == "S3a", (
        f"T8 expected S3a (A1 content_root mismatch), got {result.step}: "
        f"{result.message}"
    )
    assert "content_root" in result.message
