"""`kb/publish/0.1` — seal a draft into a signed pack tarball.

Populates the four attestation bodies (reusing the distill report
for the redaction attestation), runs `kb_pack.build_pack` to compute
roots + sign everything, and finally writes a deterministic tarball
at `published/<pack_id>-<version>.tar`.

The signed directory stays on disk under `drafts/<pack_id>/` so the
publisher can re-export or inspect it.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import mcp.types as types
import yaml

from kb_distiller import ModelFamilyError, assert_different_families
from kb_mcp_server.envelope import error, ok
from kb_mcp_server.publisher_context import (
    PublisherContextError,
    load_publisher_context,
)
from kb_pack import (
    BuildError,
    build_evaluation,
    build_license,
    build_pack,
    build_provenance,
    build_redaction,
)

TOOL = types.Tool(
    name="kb/publish/0.1",
    description=(
        "Seal drafts/<pack_id>/ into a signed pack tarball under published/. "
        "Reads .distill-report.json to populate the redaction attestation; "
        "the other three attestations are filled from the manifest + default "
        "license from policy.yaml."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "pack_id": {"type": "string"},
            "composite_score": {
                "type": "number",
                "description": "Optional evaluator composite score to record.",
                "default": 0.0,
            },
        },
        "required": ["pack_id"],
        "additionalProperties": False,
    },
)

REPORT_FILE = ".distill-report.json"


def _load_manifest(draft_dir: Path) -> dict[str, Any]:
    return yaml.safe_load(
        (draft_dir / "pack.manifest.yaml").read_text(encoding="utf-8")
    )


def _load_policy(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / ".kb" / "policy.yaml").read_text(encoding="utf-8"))


def _enforce_verifier_family_policy(
    block: dict[str, Any], policy: dict[str, Any]
) -> None:
    """If publisher policy demands a different model family for the
    adversarial verifier, refuse to seal a redaction attestation whose
    `adversarial_verification` block names two same-family models.

    The skill cannot lie its way past this — even if it stamps a
    fraudulent block, publish refuses. Spec §10 invariant.
    """
    if not policy.get("publisher", {}).get(
        "adversarial_verifier_model_family_must_differ", False
    ):
        return
    redactor = block.get("redactor_model")
    verifier = block.get("verifier_model")
    if not redactor or not verifier:
        raise BuildError(
            "policy demands adversarial_verifier_model_family_must_differ but "
            "the .distill-report.json adversarial_verification block is "
            "missing redactor_model or verifier_model."
        )
    try:
        assert_different_families(redactor, verifier)
    except ModelFamilyError as exc:
        raise BuildError(str(exc)) from exc


def _populate_attestations(
    draft_dir: Path,
    manifest: dict[str, Any],
    policy: dict[str, Any],
    composite_score: float,
    publisher_id: str,
) -> None:
    pack_ref = f"{manifest['pack_id']}@{manifest['version']}"
    placeholder_root = "sha256:placeholder"  # build_pack overwrites with real root
    atts_dir = draft_dir / "attestations"

    # provenance
    page_files = sorted((draft_dir / "pages").glob("*.md"))
    prov = build_provenance(
        pack_ref=pack_ref,
        content_root=placeholder_root,
        issuer=publisher_id,
        source_documents=len(page_files),
        source_types=["wiki-slice"],
    )
    (atts_dir / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")

    # redaction — reuse distill report
    report_path = draft_dir / REPORT_FILE
    if not report_path.is_file():
        raise BuildError(
            f"No {REPORT_FILE} in draft; run kb/distill/0.1 before publish."
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    redaction_level = report.get("redaction_level", "minimal")
    categories = report.get("categories_redacted", [])
    residual = report.get("residual_risk_notes") or [
        "No residual risk enumerated."
    ]
    policy_id = policy.get("publisher", {}).get(
        "distiller_mode", redaction_level
    )
    policy_version = policy.get("policy_version", "kbtransfer/0.1")
    llm_assisted_by = report.get("llm_assisted_by")
    adversarial_verification = report.get("adversarial_verification")
    if adversarial_verification is not None:
        _enforce_verifier_family_policy(adversarial_verification, policy)
    red = build_redaction(
        pack_ref=pack_ref,
        content_root=placeholder_root,
        issuer=publisher_id,
        redaction_level=redaction_level,
        policy_id=f"kbtransfer-{policy_id}",
        policy_version=policy_version,
        residual_risk_notes=residual,
        categories_redacted=categories,
        llm_assisted_by=llm_assisted_by,
        adversarial_verification=adversarial_verification,
    )
    (atts_dir / "redaction.json").write_text(json.dumps(red), encoding="utf-8")

    # evaluation
    ev = build_evaluation(
        pack_ref=pack_ref,
        content_root=placeholder_root,
        issuer=publisher_id,
        composite_score=composite_score,
        evaluators=[
            {
                "role": "publisher-self-assessment",
                "composite_score": composite_score,
            }
        ],
        test_cases={"pass_rate": 0.0, "total": 0},
    )
    (atts_dir / "evaluation.json").write_text(json.dumps(ev), encoding="utf-8")

    # license
    spdx = manifest.get("license", {}).get("spdx") or policy.get("publisher", {}).get(
        "default_license", "Apache-2.0"
    )
    license_class = "permissive" if spdx.lower() in {"apache-2.0", "mit"} else "commercial-with-warranty"
    lic = build_license(
        pack_ref=pack_ref,
        content_root=placeholder_root,
        issuer=publisher_id,
        license_spdx=spdx,
        license_class=license_class,
        grants=["internal-use", "private-derivatives"],
        restrictions=[],
        warranty=None,
    )
    (atts_dir / "license.json").write_text(json.dumps(lic), encoding="utf-8")


def _make_tarball(draft_dir: Path, out_dir: Path, pack_id: str, version: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"{pack_id}-{version}.tar"
    # Deterministic-ish tar: sorted entries, no pax timestamps beyond what
    # tarfile does by default. Phase 2 does not claim reproducible
    # tarballs across platforms; that's v0.2 (spec §15).
    with tarfile.open(tar_path, "w") as tar:
        for path in sorted(draft_dir.rglob("*")):
            if path.name == REPORT_FILE:
                continue
            arcname = f"{pack_id}-{version}/" + str(path.relative_to(draft_dir))
            tar.add(path, arcname=arcname, recursive=False)
    return tar_path


async def HANDLER(root: Path, arguments: dict[str, Any]) -> list[types.TextContent]:
    root = root.resolve()
    pack_id = arguments.get("pack_id")
    composite_score = float(arguments.get("composite_score") or 0.0)
    if not isinstance(pack_id, str) or not pack_id:
        return error("invalid_pack_id", "Argument 'pack_id' must be a non-empty string.")

    draft_dir = root / "drafts" / pack_id
    if not draft_dir.is_dir():
        return error("draft_missing", f"No draft at drafts/{pack_id}")

    try:
        ctx = load_publisher_context(root)
    except PublisherContextError as exc:
        return error("publisher_context_missing", str(exc))

    try:
        manifest = _load_manifest(draft_dir)
    except Exception as exc:
        return error("manifest_invalid", f"Could not parse pack.manifest.yaml: {exc}")
    policy = _load_policy(root)

    try:
        _populate_attestations(
            draft_dir,
            manifest=manifest,
            policy=policy,
            composite_score=composite_score,
            publisher_id=ctx.publisher_id,
        )
    except BuildError as exc:
        return error("distill_report_missing", str(exc))

    # The distill report is a build-time artifact, not part of the
    # published pack. Remove it before computing the pack_root so the
    # draft on disk matches what we ship in the tarball.
    report_path = draft_dir / REPORT_FILE
    if report_path.is_file():
        report_path.unlink()

    try:
        result = build_pack(
            draft_dir,
            key_id=ctx.key_id,
            private_key_hex=ctx.private_key_hex,
            public_key_hex=ctx.public_key_hex,
        )
    except BuildError as exc:
        return error("build_failed", str(exc))

    version = manifest.get("version", "0.0.0")
    tar_path = _make_tarball(draft_dir, root / "published", pack_id, version)

    return ok(
        {
            "pack_id": pack_id,
            "version": version,
            "content_root": result.content_root,
            "pack_root": result.pack_root,
            "signed_draft": f"drafts/{pack_id}",
            "tarball": str(tar_path.relative_to(root)),
            "attestations": {
                kind: str(path.relative_to(root))
                for kind, path in result.attestation_paths.items()
            },
        }
    )
