"""Trust store helpers for resolving publisher keys during verification.

Shape of `.kb/trust-store.yaml` (matches the template shipped by
`kb init`):

    trust_store_version: "kbtransfer/0.1"
    publishers:
      did:web:foo.example:
        display_name: "Foo Inc"
        keys:
          - key_id: "foo-2026Q2"
            algorithm: "ed25519"
            public_key_hex: "..."
            valid_from: "..."
            added_at: "..."

The individual + team tiers use TOFU: newly-seen publishers are
auto-registered on first subscribe. The enterprise tier's policy
disables TOFU and requires an explicit entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from kb_pack import PublisherKeyResolver

TRUST_STORE_PATH = ".kb/trust-store.yaml"


def _path(kb_root: Path) -> Path:
    return kb_root / TRUST_STORE_PATH


def load_trust_store(kb_root: Path) -> dict[str, Any]:
    path = _path(kb_root)
    if not path.is_file():
        return {"trust_store_version": "kbtransfer/0.1", "publishers": {}}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    doc.setdefault("publishers", {})
    if not isinstance(doc["publishers"], dict):
        doc["publishers"] = {}
    return doc


def save_trust_store(kb_root: Path, doc: dict[str, Any]) -> None:
    _path(kb_root).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def resolver_from_trust_store(kb_root: Path) -> PublisherKeyResolver:
    resolver = PublisherKeyResolver()
    store = load_trust_store(kb_root)
    for publisher_id, record in (store.get("publishers") or {}).items():
        if not isinstance(record, dict):
            continue
        for key in record.get("keys") or []:
            if not isinstance(key, dict):
                continue
            key_id = key.get("key_id")
            pubhex = key.get("public_key_hex")
            if key_id and pubhex:
                resolver.register(publisher_id, key_id, pubhex)
    return resolver


def register_publisher_key(
    kb_root: Path,
    publisher_id: str,
    key_id: str,
    public_key_hex: str,
    display_name: str | None = None,
    origin: str = "subscribe",
) -> dict[str, Any]:
    store = load_trust_store(kb_root)
    publishers = store.setdefault("publishers", {})
    record = publishers.setdefault(publisher_id, {})
    if display_name and not record.get("display_name"):
        record["display_name"] = display_name
    keys = record.setdefault("keys", [])
    for existing in keys:
        if isinstance(existing, dict) and existing.get("key_id") == key_id:
            if existing.get("public_key_hex") != public_key_hex:
                existing["public_key_hex"] = public_key_hex
                existing["updated_at"] = _now()
                existing["updated_via"] = origin
            save_trust_store(kb_root, store)
            return store
    keys.append(
        {
            "key_id": key_id,
            "algorithm": "ed25519",
            "public_key_hex": public_key_hex,
            "added_at": _now(),
            "added_via": origin,
        }
    )
    save_trust_store(kb_root, store)
    return store


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
