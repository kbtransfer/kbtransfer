"""Canonical JSON serialization per AutoEvolve pack spec v0.1.1 Appendix A.

This is `canonical-2026-04`, a deterministic subset of RFC 8785. It
is used for every signed attestation and for any hash input that
must round-trip byte-identically between publisher and consumer.

Rules (summarized from Appendix A):

1. UTF-8, no BOM.
2. Object keys sorted lexicographically by UTF-8 byte order.
3. Separators: ',' and ':' with no whitespace.
4. String escapes: only the JSON standard short escapes plus
   `\\uXXXX` for control characters; other code points emitted
   directly.
5. NaN / +Infinity / -Infinity rejected.
6. Arrays preserve order.

The reference Python form stated by the spec (Appendix A) is the
two-liner below. v0.2 will commit to full RFC 8785; do not over-
engineer here.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
