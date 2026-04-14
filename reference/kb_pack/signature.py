"""Ed25519 envelope signatures per spec v0.1.1 §5.2 (amendment A5).

Every signature is a JSON object with three fields:

    {"algorithm": "ed25519", "key_id": "...", "value": "<hex>"}

Two signing scopes:

- **Attestation signatures.** The signed bytes are the canonical-JSON
  serialization of the attestation WITH THE `signature` FIELD REMOVED
  (amendment B2). Consumer recomputes the same canonical form,
  removes `signature`, and verifies the hex value.

- **Publisher signature over pack_root.** The signed bytes are
  `b"autoevolve-pack/0.1.1\\n" + pack_root_hex.encode("ascii")`
  (spec §4). Shipped as the raw signature bytes under
  `signatures/publisher.sig` alongside `signatures/publisher.pubkey`.

Only ed25519 is accepted in v0.1.1. Envelopes declaring any other
algorithm are rejected at verification time.
"""

from __future__ import annotations

import copy
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from kb_pack.canonical import canonical_json

ALGORITHM = "ed25519"
PACK_SIG_PREFIX = b"autoevolve-pack/0.1.1\n"


def _load_private(private_key_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))


def _load_public(public_key_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))


def sign_bytes(private_key_hex: str, payload: bytes) -> str:
    signature = _load_private(private_key_hex).sign(payload)
    return signature.hex()


def verify_bytes(public_key_hex: str, payload: bytes, signature_hex: str) -> bool:
    try:
        _load_public(public_key_hex).verify(bytes.fromhex(signature_hex), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def make_envelope(key_id: str, value_hex: str) -> dict[str, str]:
    return {"algorithm": ALGORITHM, "key_id": key_id, "value": value_hex}


def validate_envelope(envelope: Any) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("signature envelope must be an object")
    if envelope.get("algorithm") != ALGORITHM:
        raise ValueError(
            f"unsupported signature algorithm {envelope.get('algorithm')!r} "
            f"(v0.1.1 accepts only {ALGORITHM!r})"
        )
    if not isinstance(envelope.get("key_id"), str) or not envelope["key_id"]:
        raise ValueError("signature envelope missing key_id")
    if not isinstance(envelope.get("value"), str) or not envelope["value"]:
        raise ValueError("signature envelope missing value")


def sign_attestation(
    attestation: dict[str, Any],
    key_id: str,
    private_key_hex: str,
) -> dict[str, Any]:
    unsigned = copy.deepcopy(attestation)
    unsigned.pop("signature", None)
    payload = canonical_json(unsigned)
    value_hex = sign_bytes(private_key_hex, payload)
    attestation["signature"] = make_envelope(key_id, value_hex)
    return attestation


def verify_attestation_signature(
    attestation: dict[str, Any],
    public_key_hex: str,
) -> bool:
    envelope = attestation.get("signature")
    validate_envelope(envelope)
    unsigned = {k: v for k, v in attestation.items() if k != "signature"}
    payload = canonical_json(unsigned)
    return verify_bytes(public_key_hex, payload, envelope["value"])


def sign_pack_root(pack_root_hex: str, private_key_hex: str) -> bytes:
    payload = PACK_SIG_PREFIX + pack_root_hex.encode("ascii")
    signature = _load_private(private_key_hex).sign(payload)
    return signature


def verify_pack_root(
    pack_root_hex: str,
    signature_bytes: bytes,
    public_key_hex: str,
) -> bool:
    payload = PACK_SIG_PREFIX + pack_root_hex.encode("ascii")
    try:
        _load_public(public_key_hex).verify(signature_bytes, payload)
        return True
    except (InvalidSignature, ValueError):
        return False
