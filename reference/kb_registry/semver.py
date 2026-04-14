"""Minimum viable semver matcher for Phase 3 dependency resolution.

Supports the constraint forms the AutoEvolve registry spec §3.3
refers to:

    "1.2.3"    exact
    "=1.2.3"   exact (explicit)
    "^1.2.3"   compatible major (>=1.2.3, <2.0.0)
    "~1.2.3"   compatible minor (>=1.2.3, <1.3.0)
    ">=1.2.3"  at-least
    "*"        any

Pre-release / build-metadata suffixes are not handled in v1; versions
must match `^\\d+\\.\\d+\\.\\d+$`. Production installs should swap
this out for `packaging.version`; the tiny local implementation is
deliberate so Phase 3 has zero runtime deps beyond cryptography +
pyyaml + mcp + click.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise ValueError(f"invalid version: {text!r}")
        return cls(*(int(x) for x in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _pad(text: str) -> str:
    """Zero-pad shorthand like '1.0' to '1.0.0' so constraints can
    abbreviate the minor/patch. Versions stored in the registry must
    still be fully qualified (see Version.parse)."""
    parts = text.strip().split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts)


def _parse_operator(constraint: str) -> tuple[str, Version]:
    constraint = constraint.strip()
    if constraint == "*":
        return "*", Version(0, 0, 0)
    for op in ("^", "~", ">=", "="):
        if constraint.startswith(op):
            return op, Version.parse(_pad(constraint[len(op):]))
    # No operator -> exact match.
    return "=", Version.parse(_pad(constraint))


def matches(version: str, constraint: str) -> bool:
    v = Version.parse(version)
    op, base = _parse_operator(constraint)
    if op == "*":
        return True
    if op == "=":
        return v == base
    if op == ">=":
        return v >= base
    if op == "~":
        return (
            v.major == base.major
            and v.minor == base.minor
            and v.patch >= base.patch
        )
    if op == "^":
        return v >= base and v.major == base.major
    raise ValueError(f"unknown constraint operator: {op}")


def highest_matching(versions: list[str], constraint: str) -> str | None:
    eligible = [Version.parse(v) for v in versions if matches(v, constraint)]
    if not eligible:
        return None
    return str(max(eligible))
