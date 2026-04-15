"""RegistryServer — glues validation + storage into one submit path."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from kb_registry.index import write_index

from kb_registry_server.validation import (
    SubmissionValidation,
    ValidationError,
    validate_submission_bytes,
)


_VALID_ROLES = frozenset({"open", "consortium", "private"})
_VALID_COMMIT_MODES = frozenset({"auto", "stage"})


@dataclass(frozen=True)
class ServerConfig:
    registry_root: Path
    trust_role: str = "open"
    allowlist: frozenset[str] = frozenset()
    bearer_tokens: frozenset[str] = frozenset()
    commit_mode: str = "auto"
    max_bytes: int = 256 * 1024 * 1024
    registry_id: str = ""

    def __post_init__(self) -> None:
        if self.trust_role not in _VALID_ROLES:
            raise ValueError(
                f"trust_role must be one of {sorted(_VALID_ROLES)}, "
                f"got {self.trust_role!r}"
            )
        if self.commit_mode not in _VALID_COMMIT_MODES:
            raise ValueError(
                f"commit_mode must be one of {sorted(_VALID_COMMIT_MODES)}, "
                f"got {self.commit_mode!r}"
            )
        if self.trust_role == "private" and not self.bearer_tokens:
            raise ValueError(
                "private trust_role requires at least one bearer token in config"
            )


@dataclass
class SubmissionResult:
    accepted: bool
    pack_id: str | None = None
    version: str | None = None
    publisher_id: str | None = None
    canonical_path: str | None = None
    received_at: str = ""
    checks_passed: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    commit_mode: str = "auto"

    def to_wire(self) -> dict[str, object]:
        if self.accepted:
            payload: dict[str, object] = {
                "accepted": True,
                "pack_id": self.pack_id,
                "version": self.version,
                "publisher_id": self.publisher_id,
                "received_at": self.received_at,
                "canonical_path": self.canonical_path,
                "checks_passed": list(self.checks_passed),
                "commit_mode": self.commit_mode,
            }
            return payload
        return {
            "accepted": False,
            "received_at": self.received_at,
            "errors": list(self.errors),
        }


def _iso_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class RegistryServer:
    """Reusable submit handler. Thread-safe under a single-process lock."""

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        root = config.registry_root.resolve()
        if not root.is_dir():
            raise ValueError(f"registry_root is not a directory: {root}")
        self._root = root
        self._lock = threading.Lock()

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def registry_root(self) -> Path:
        return self._root

    def submit(
        self,
        tar_bytes: bytes,
        *,
        bearer_token: str | None = None,
        notes: str = "",
    ) -> SubmissionResult:
        received_at = _iso_utc_now()

        if self._config.trust_role == "private":
            if not bearer_token or bearer_token not in self._config.bearer_tokens:
                return SubmissionResult(
                    accepted=False,
                    received_at=received_at,
                    errors=[
                        {
                            "check": "bearer_token",
                            "message": "private registry requires a valid bearer token",
                            "remediation": "include Authorization: Bearer <token> header",
                        }
                    ],
                )

        try:
            validation = validate_submission_bytes(
                tar_bytes,
                self._root,
                max_bytes=self._config.max_bytes,
                trust_role=self._config.trust_role,
                allowlist=self._config.allowlist,
            )
        except ValidationError as exc:
            return SubmissionResult(
                accepted=False,
                received_at=received_at,
                errors=[exc.to_wire()],
            )

        with self._lock:
            try:
                canonical_path = _commit_submission(
                    validation,
                    self._root,
                    commit_mode=self._config.commit_mode,
                )
            except ValidationError as exc:
                return SubmissionResult(
                    accepted=False,
                    received_at=received_at,
                    errors=[exc.to_wire()],
                )
            if self._config.commit_mode == "auto":
                write_index(self._root)

        return SubmissionResult(
            accepted=True,
            pack_id=validation.pack_id,
            version=validation.version,
            publisher_id=validation.publisher_id,
            canonical_path=str(canonical_path.relative_to(self._root)),
            received_at=received_at,
            checks_passed=list(validation.checks_passed),
            commit_mode=self._config.commit_mode,
        )


def _commit_submission(
    validation: SubmissionValidation,
    registry_root: Path,
    *,
    commit_mode: str,
) -> Path:
    if commit_mode == "auto":
        target_dir = registry_root / "packs" / validation.pack_id
        target_path = target_dir / f"{validation.version}.tar"
    else:
        target_dir = registry_root / "submissions" / validation.pack_id
        target_path = target_dir / f"{validation.version}.tar.pending"
    target_dir.mkdir(parents=True, exist_ok=True)

    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
    try:
        fd = os.open(target_path, flags, 0o644)
    except FileExistsError as exc:
        raise ValidationError(
            "version_uniqueness",
            f"{validation.pack_id}@{validation.version} already exists "
            f"(won race or staged duplicate)",
            "bump the pack version per semver and re-publish",
        ) from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(validation.tar_bytes)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    return target_path
