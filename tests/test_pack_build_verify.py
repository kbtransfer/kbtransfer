"""End-to-end build + verify tests for kb_pack."""

from __future__ import annotations

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
    verify_pack,
)


PACK_ID = "example.phase2"
VERSION = "1.0.0"
PUBLISHER = "did:web:example.invalid"


def _manifest_doc() -> dict:
    return {
        "spec_version": "autoevolve-pack/0.1.1",
        "pack_id": PACK_ID,
        "version": VERSION,
        "namespace": "example.phase2",
        "publisher": {"id": PUBLISHER, "display_name": "Example"},
        "title": "Phase 2 build/verify fixture",
        "summary": "Minimum viable pack for exercising the full build and verify chain.",
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
    (pack_dir / "README.md").write_text(
        f"# {PACK_ID}\n\nIntegration fixture.\n", encoding="utf-8"
    )
    (pack_dir / "pages" / "pattern.md").write_text(
        "# Pattern\n\nBody with meaningful content.\n", encoding="utf-8"
    )

    # Attestation stubs. content_root + signature are injected by build_pack.
    prov = build_provenance(
        pack_ref=f"{PACK_ID}@{VERSION}",
        content_root="sha256:placeholder",
        issuer=PUBLISHER,
        source_documents=2,
        source_types=["internal-doc"],
    )
    red = build_redaction(
        pack_ref=f"{PACK_ID}@{VERSION}",
        content_root="sha256:placeholder",
        issuer=PUBLISHER,
        redaction_level="minimal",
        policy_id="example-minimal",
        policy_version="1.0.0",
        residual_risk_notes=["Public-source stylometric features may survive paraphrase."],
    )
    ev = build_evaluation(
        pack_ref=f"{PACK_ID}@{VERSION}",
        content_root="sha256:placeholder",
        issuer=PUBLISHER,
        composite_score=0.9,
    )
    lic = build_license(
        pack_ref=f"{PACK_ID}@{VERSION}",
        content_root="sha256:placeholder",
        issuer=PUBLISHER,
        license_spdx="Apache-2.0",
        license_class="permissive",
    )
    for kind, doc in (("provenance", prov), ("redaction", red),
                      ("evaluation", ev), ("license", lic)):
        (pack_dir / "attestations" / f"{kind}.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )


@pytest.fixture
def signed_pack(tmp_path: Path) -> tuple[Path, PublisherKeyResolver]:
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
    return pack_dir, resolver


def test_build_then_verify_happy_path(signed_pack) -> None:
    pack_dir, resolver = signed_pack
    result = verify_pack(pack_dir, resolver)
    assert result.ok, result.message
    assert result.content_root.startswith("sha256:")
    assert result.pack_root.startswith("sha256:")
    assert set(result.attestations.keys()) == {"provenance", "redaction",
                                                 "evaluation", "license"}
    for att in result.attestations.values():
        assert att["content_root"] == result.content_root
        assert att["signature"]["algorithm"] == "ed25519"


def test_all_attestations_bind_to_same_content_root(signed_pack) -> None:
    pack_dir, _ = signed_pack
    roots = set()
    for kind in ("provenance", "redaction", "evaluation", "license"):
        att_path = pack_dir / "attestations" / f"{kind}.json"
        data = json.loads(att_path.read_text())
        roots.add(data["content_root"])
    assert len(roots) == 1


def test_verifier_rejects_unknown_publisher(signed_pack) -> None:
    pack_dir, _ = signed_pack
    empty_resolver = PublisherKeyResolver()  # no trusted keys at all
    result = verify_pack(pack_dir, empty_resolver)
    assert not result.ok
    assert result.step == "S3b"
    assert "untrusted issuer" in result.message


def test_verifier_rejects_when_bundled_pubkey_differs(signed_pack, tmp_path: Path) -> None:
    pack_dir, resolver = signed_pack
    # Swap the bundled public key for a different (valid ed25519) one.
    decoy = generate_keypair(publisher_id=PUBLISHER)
    (pack_dir / "signatures" / "publisher.pubkey").write_bytes(
        bytes.fromhex(decoy.public_key_hex)
    )
    result = verify_pack(pack_dir, resolver)
    assert not result.ok
    assert result.step == "S5"
