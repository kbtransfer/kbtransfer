"""Registry-side submit handling per RFC-0002.

Reusable library a concrete HTTP server (e.g. the FastAPI shim under
`examples/sample-registry-http/`) can import. Pure stdlib + existing
reference packages; no web framework in this layer.

Flow:

    server.submit(tar_bytes, ...) -> SubmissionResult

Internally runs RFC-0002 §4 validation against the pack, then either
writes the accepted tarball into the registry's filesystem layout
and rebuilds index.json (commit_mode="auto") or stages it for a human
operator to promote later (commit_mode="stage").

Rejected submissions are never stored: if any check fails the
in-memory bytes are dropped and the filesystem is untouched.
"""

from __future__ import annotations

__version__ = "0.1.0"

from kb_registry_server.server import RegistryServer, ServerConfig, SubmissionResult
from kb_registry_server.validation import (
    CHECK_NAMES,
    SubmissionValidation,
    ValidationError,
    validate_submission_bytes,
)

__all__ = [
    "CHECK_NAMES",
    "RegistryServer",
    "ServerConfig",
    "SubmissionResult",
    "SubmissionValidation",
    "ValidationError",
    "validate_submission_bytes",
]
