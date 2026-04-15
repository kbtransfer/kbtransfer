"""D8 adversarial suite — abuse paths for RFC-0002 registry submit."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from kb_registry import write_index
from kb_registry_server import (
    RegistryServer,
    ServerConfig,
    ValidationError,
    validate_submission_bytes,
)


@pytest.fixture
def empty_registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    (root / "packs").mkdir(parents=True)
    (root / "publishers").mkdir(parents=True)
    write_index(root)
    return root


def _build_traversal_tarball(target_relative: str) -> bytes:
    """Construct a tar containing a single member whose path escapes the prefix."""
    buf = io.BytesIO()
    payload = b"totally innocuous bytes"
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=target_relative)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def test_d8_01_path_traversal_absolute_rejected_before_extract(
    tmp_path: Path, empty_registry: Path
) -> None:
    evil = _build_traversal_tarball("/etc/passwd")
    with pytest.raises(ValidationError) as exc:
        validate_submission_bytes(evil, empty_registry)
    assert exc.value.check == "tar_safe_extract"
    # No file was created outside the staging tmpdir.
    assert not (tmp_path / "etc").exists()


def test_d8_02_path_traversal_parent_ref_rejected(
    empty_registry: Path,
) -> None:
    evil = _build_traversal_tarball("foo/../../bar")
    with pytest.raises(ValidationError) as exc:
        validate_submission_bytes(evil, empty_registry)
    assert exc.value.check == "tar_safe_extract"


def test_d8_03_oversize_rejected_before_extract(empty_registry: Path) -> None:
    # 1 MiB of zeros — well below the default cap but above our test cap.
    big = b"\x00" * (1024 * 1024)
    with pytest.raises(ValidationError) as exc:
        validate_submission_bytes(big, empty_registry, max_bytes=1024)
    assert exc.value.check == "size_limit"


def test_d8_04_multiple_top_level_dirs_rejected(empty_registry: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for folder in ("a", "b"):
            info = tarfile.TarInfo(name=f"{folder}/file.txt")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"hi"))
    with pytest.raises(ValidationError) as exc:
        validate_submission_bytes(buf.getvalue(), empty_registry)
    assert exc.value.check == "tar_safe_extract"


def test_d8_05_non_tar_bytes_rejected_as_tar_safe_extract(
    empty_registry: Path,
) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_submission_bytes(b"not a tar at all", empty_registry)
    assert exc.value.check == "tar_safe_extract"


def test_d8_06_replay_submit_is_rejected_as_duplicate(
    tmp_path: Path, empty_registry: Path
) -> None:
    # Reuse the publish helpers from the library test to get a valid tarball.
    from tests.test_registry_submit import _build_pack, _install_publisher_keys

    publisher_id = "did:web:replay.example"
    tar_path = _build_pack(tmp_path, "replay.pack", "1.0.0", publisher_id)
    kb_root = tar_path.parents[1]
    _install_publisher_keys(empty_registry, publisher_id, kb_root)

    server = RegistryServer(ServerConfig(registry_root=empty_registry))
    first = server.submit(tar_path.read_bytes())
    assert first.accepted, first.errors
    second = server.submit(tar_path.read_bytes())
    assert not second.accepted
    assert second.errors[0]["check"] == "version_uniqueness"
    # Only one copy of the tarball on disk.
    copies = list((empty_registry / "packs" / "replay.pack").glob("*.tar"))
    assert len(copies) == 1
