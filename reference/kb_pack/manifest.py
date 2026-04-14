"""`pack.manifest.yaml` loading and minimal validation.

Per spec v0.1.1 §3, the manifest is a YAML document with the fields
listed in REQUIRED_FIELDS. Extra fields are preserved verbatim.

`lock_hash` is explicitly NOT a field (amendment A2). Binding comes
from the publisher signature over pack_root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SPEC_VERSION = "autoevolve-pack/0.1.1"

REQUIRED_FIELDS = (
    "spec_version",
    "pack_id",
    "version",
    "namespace",
    "publisher",
    "title",
    "attestations",
    "policy_surface",
)

REQUIRED_ATTESTATIONS = ("provenance", "redaction", "evaluation", "license")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    doc: dict[str, Any]

    @property
    def pack_id(self) -> str:
        return self.doc["pack_id"]

    @property
    def version(self) -> str:
        return self.doc["version"]

    @property
    def publisher_id(self) -> str:
        return self.doc["publisher"]["id"]

    @property
    def spec_version(self) -> str:
        return self.doc["spec_version"]

    @property
    def attestation_paths(self) -> dict[str, str]:
        return dict(self.doc["attestations"])

    @property
    def pack_ref(self) -> str:
        return f"{self.pack_id}@{self.version}"


def load_manifest(pack_root: Path) -> Manifest:
    path = pack_root / "pack.manifest.yaml"
    if not path.is_file():
        raise ManifestError(f"Missing pack.manifest.yaml at {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"pack.manifest.yaml parse error: {exc}") from exc
    if not isinstance(doc, dict):
        raise ManifestError("pack.manifest.yaml did not parse to a mapping")
    validate(doc)
    return Manifest(doc=doc)


def validate(doc: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in doc]
    if missing:
        raise ManifestError(f"Manifest missing required fields: {missing}")
    if doc["spec_version"] != SPEC_VERSION:
        raise ManifestError(
            f"spec_version {doc['spec_version']!r} does not match expected {SPEC_VERSION!r}"
        )
    publisher = doc.get("publisher")
    if not isinstance(publisher, dict) or "id" not in publisher:
        raise ManifestError("publisher.id is required")
    attestations = doc.get("attestations")
    if not isinstance(attestations, dict):
        raise ManifestError("attestations must be a mapping of kind -> path")
    missing_att = [kind for kind in REQUIRED_ATTESTATIONS if kind not in attestations]
    if missing_att:
        raise ManifestError(f"attestations block missing kinds: {missing_att}")
    if "lock_hash" in doc:
        raise ManifestError(
            "manifest contains lock_hash; removed by amendment A2 in spec v0.1.1"
        )
