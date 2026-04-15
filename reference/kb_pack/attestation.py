"""Attestation construction and loading per spec v0.1.1 §5.

The four attestation kinds share a common envelope:

    {
      "spec": "autoevolve-attestation/{kind}/0.1.1",
      "pack": "{pack_id}@{version}",
      "content_root": "sha256:<hex>",
      "issuer": "{did}",
      "issued_at": "{iso8601Z}",
      ... kind-specific body ...,
      "signature": {"algorithm": "ed25519", "key_id": "...", "value": "..."}
    }

Per amendment A1, every attestation's `content_root` MUST equal the
pack's `content_root`. Per amendment C1, a redaction attestation's
`residual_risk_notes` MUST be a non-empty list.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kb_pack.canonical import canonical_json

KINDS = ("provenance", "redaction", "evaluation", "license")


class AttestationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_sha256_prefix(root_hex: str) -> str:
    return root_hex if root_hex.startswith("sha256:") else f"sha256:{root_hex}"


def build_envelope(
    kind: str,
    pack_ref: str,
    content_root: str,
    issuer: str,
    issued_at: str | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise AttestationError(f"unknown attestation kind: {kind!r}")
    return {
        "spec": f"autoevolve-attestation/{kind}/0.1.1",
        "pack": pack_ref,
        "content_root": _ensure_sha256_prefix(content_root),
        "issuer": issuer,
        "issued_at": issued_at or _now_iso(),
    }


def build_provenance(
    pack_ref: str,
    content_root: str,
    issuer: str,
    source_documents: int,
    source_types: list[str],
    build_environment: str = "kbtransfer-v0.1.0",
    issued_at: str | None = None,
) -> dict[str, Any]:
    doc = build_envelope("provenance", pack_ref, content_root, issuer, issued_at)
    doc["derived_from"] = {
        "source_documents": source_documents,
        "source_types": list(source_types),
    }
    doc["build_environment"] = build_environment
    return doc


def build_redaction(
    pack_ref: str,
    content_root: str,
    issuer: str,
    redaction_level: str,
    policy_id: str,
    policy_version: str,
    residual_risk_notes: list[str],
    categories_redacted: list[str] | None = None,
    human_review: dict[str, Any] | None = None,
    adversarial_verification: dict[str, Any] | None = None,
    llm_assisted_by: dict[str, Any] | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    if not residual_risk_notes:
        raise AttestationError(
            "redaction.residual_risk_notes must be non-empty (amendment C1)"
        )
    doc = build_envelope("redaction", pack_ref, content_root, issuer, issued_at)
    doc["redaction_level"] = redaction_level
    doc["policy_applied"] = policy_id
    doc["policy_version"] = policy_version
    doc["categories_redacted"] = list(categories_redacted or [])
    doc["residual_risk_notes"] = list(residual_risk_notes)
    if human_review is not None:
        doc["human_review"] = dict(human_review)
    if adversarial_verification is not None:
        doc["adversarial_verification"] = dict(adversarial_verification)
    if llm_assisted_by is not None:
        # Transparency field: when an agent skill (single-model team-tier
        # pipeline or dual-model enterprise pipeline) drove paraphrase /
        # redaction passes via an LLM, the skill records its model
        # identity, iteration count, and (for dual-model) the verifier
        # model. Consumers can then weigh the attestation knowing whether
        # an LLM rewrote the content vs whether a human did.
        doc["llm_assisted_by"] = dict(llm_assisted_by)
    return doc


def build_evaluation(
    pack_ref: str,
    content_root: str,
    issuer: str,
    evaluators: list[dict[str, Any]] | None = None,
    test_cases: dict[str, Any] | None = None,
    composite_score: float | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    doc = build_envelope("evaluation", pack_ref, content_root, issuer, issued_at)
    doc["evaluators"] = list(evaluators or [])
    doc["test_cases"] = dict(test_cases or {})
    if composite_score is not None:
        doc["composite_score"] = composite_score
    doc["third_party_review"] = None
    return doc


def build_license(
    pack_ref: str,
    content_root: str,
    issuer: str,
    license_spdx: str,
    license_class: str,
    grants: list[str] | None = None,
    restrictions: list[str] | None = None,
    warranty: str | None = None,
    issued_at: str | None = None,
) -> dict[str, Any]:
    doc = build_envelope("license", pack_ref, content_root, issuer, issued_at)
    doc["license_spdx"] = license_spdx
    doc["license_class"] = license_class
    doc["grants"] = list(grants or [])
    doc["restrictions"] = list(restrictions or [])
    if warranty is not None:
        doc["warranty"] = warranty
    return doc


def write_attestation(path: Path, attestation: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(attestation))


def load_attestation(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
