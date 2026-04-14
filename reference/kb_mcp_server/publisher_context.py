"""Publisher identity + active signing key resolution for this KB.

`kb init` writes .kb/tier.yaml with `tier`, `publisher_id`, and
`signing_key_id`. The signing key's bytes live under .kb/keys/ as
two YAML sidecars produced by kb_cli.keygen (one .pub, one .priv).

This module reads both and exposes a typed handle for publish-time
use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

TIER_PATH = ".kb/tier.yaml"
KEYS_DIR = ".kb/keys"


class PublisherContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublisherContext:
    tier: str
    publisher_id: str
    key_id: str
    public_key_hex: str
    private_key_hex: str


def load_publisher_context(kb_root: Path) -> PublisherContext:
    tier_path = kb_root / TIER_PATH
    if not tier_path.is_file():
        raise PublisherContextError(f"Missing {TIER_PATH}")
    tier_doc = yaml.safe_load(tier_path.read_text(encoding="utf-8")) or {}
    tier = tier_doc.get("tier")
    publisher_id = tier_doc.get("publisher_id")
    key_id = tier_doc.get("signing_key_id")
    if not all([tier, publisher_id, key_id]):
        raise PublisherContextError(
            f"{TIER_PATH} must declare tier, publisher_id, and signing_key_id"
        )

    keys_dir = kb_root / KEYS_DIR
    pub_path = keys_dir / f"{key_id}.pub"
    priv_path = keys_dir / f"{key_id}.priv"
    if not pub_path.is_file() or not priv_path.is_file():
        raise PublisherContextError(
            f"Missing keypair files for key_id {key_id!r} under {KEYS_DIR}/"
        )
    pub_doc = yaml.safe_load(pub_path.read_text(encoding="utf-8")) or {}
    priv_doc = yaml.safe_load(priv_path.read_text(encoding="utf-8")) or {}
    public_key_hex = pub_doc.get("public_key_hex")
    private_key_hex = priv_doc.get("private_key_hex")
    if not public_key_hex or not private_key_hex:
        raise PublisherContextError(
            f"Key sidecar files for {key_id!r} are missing hex fields"
        )
    return PublisherContext(
        tier=tier,
        publisher_id=publisher_id,
        key_id=key_id,
        public_key_hex=public_key_hex,
        private_key_hex=private_key_hex,
    )
