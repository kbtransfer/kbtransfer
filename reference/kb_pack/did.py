"""DID ↔ filesystem-safe path encoding.

The KB server stores installed subscriptions under
`subscriptions/<publisher_did_safe>/<pack_id>/<version>/`. The
canonical DID (`did:web:example.com`) contains `:` which is a
separator in Windows paths, tolerated but confusing in POSIX tooling,
and awkward in shell globs. This module defines the one-way
canonical transform every tool uses to derive that directory name.

The encoding is intentionally lossy — `:` and `/` both map to `-`.
The original DID is not recovered from the directory name; instead
consumers that need the canonical identifier read `publisher.id`
from the installed pack's `pack.manifest.yaml`, or `.kb/trust-store.yaml`.
Keeping the transform lossy means the directory name stays readable
(`did-web-example.com`) instead of percent-encoded
(`did%3Aweb%3Aexample.com`).
"""

from __future__ import annotations

_FORBIDDEN_CHARS = frozenset({"\x00", "\\"})


def did_to_safe_path(did: str) -> str:
    """Encode a DID as a filesystem-safe directory name.

    Raises ValueError on inputs that are not DIDs or that contain
    characters the encoding cannot represent (NUL, backslash, or any
    control character).
    """
    if not isinstance(did, str) or not did.startswith("did:"):
        raise ValueError(f"not a DID: {did!r}")
    for ch in did:
        if ord(ch) < 0x20 or ch in _FORBIDDEN_CHARS:
            raise ValueError(f"unsupported character {ch!r} in DID {did!r}")
    return did.replace(":", "-").replace("/", "-")


__all__ = ["did_to_safe_path"]
