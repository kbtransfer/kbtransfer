"""Ed25519 keypair generation for a KB publisher identity.

The reference implementation uses the `cryptography` library's
Ed25519 primitives. Keys are serialized as raw 32-byte values
encoded in lowercase hexadecimal, wrapped in a minimal YAML sidecar
that records identity and lifetime metadata.

Private key files are written with mode 0o600. Public key files are
written with mode 0o644. The caller is responsible for placing the
files under a directory with appropriate permissions.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


@dataclass(frozen=True)
class KeyPair:
    key_id: str
    publisher_id: str
    public_key_hex: str
    private_key_hex: str
    created_at: str
    algorithm: str = "ed25519"


def generate_keypair(publisher_id: str, key_id: str | None = None) -> KeyPair:
    if key_id is None:
        suffix = secrets.token_hex(4)
        key_id = f"{datetime.now(UTC).strftime('%Y%m%d')}-{suffix}"

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return KeyPair(
        key_id=key_id,
        publisher_id=publisher_id,
        public_key_hex=public_bytes.hex(),
        private_key_hex=private_bytes.hex(),
        created_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def write_keypair(keys_dir: Path, keypair: KeyPair) -> tuple[Path, Path]:
    """Write a keypair to disk as two YAML sidecar files.

    Returns `(public_path, private_path)`.
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    public_path = keys_dir / f"{keypair.key_id}.pub"
    private_path = keys_dir / f"{keypair.key_id}.priv"

    public_doc = {
        "key_id": keypair.key_id,
        "publisher_id": keypair.publisher_id,
        "algorithm": keypair.algorithm,
        "public_key_hex": keypair.public_key_hex,
        "created_at": keypair.created_at,
    }
    private_doc = {
        "key_id": keypair.key_id,
        "publisher_id": keypair.publisher_id,
        "algorithm": keypair.algorithm,
        "private_key_hex": keypair.private_key_hex,
        "created_at": keypair.created_at,
    }

    public_path.write_text(yaml.safe_dump(public_doc, sort_keys=False), encoding="utf-8")
    private_path.write_text(yaml.safe_dump(private_doc, sort_keys=False), encoding="utf-8")

    os.chmod(public_path, 0o644)
    os.chmod(private_path, 0o600)

    return public_path, private_path


def load_public_key_hex(public_key_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))


def load_private_key_hex(private_key_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
