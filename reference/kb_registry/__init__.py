"""Git-based registry tooling and CI verification for KBTRANSFER."""

from __future__ import annotations

__version__ = "0.1.0"

from kb_registry.index import (
    INDEX_VERSION,
    build_index,
    read_index,
    write_index,
)
from kb_registry.registry import (
    Registry,
    RegistryError,
    ResolveResult,
    open_registry,
)
from kb_registry.semver import Version, highest_matching, matches

__all__ = [
    "INDEX_VERSION",
    "Registry",
    "RegistryError",
    "ResolveResult",
    "Version",
    "build_index",
    "highest_matching",
    "matches",
    "open_registry",
    "read_index",
    "write_index",
]
