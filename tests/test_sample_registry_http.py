"""End-to-end HTTP tests for the sample-registry-http FastAPI app.

Exercises the full RFC-0002 wire path: HttpsRegistry.submit() encodes
multipart + Authorization, FastAPI decodes it, RegistryServer validates
and commits, then a follow-up HttpsRegistry.fetch() over the same
TestClient resolves and extracts the pack a consumer would install.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kb_registry import HttpsRegistry, write_index
from kb_registry_server import RegistryServer, ServerConfig


def _load_fastapi_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "kbtransfer_sample_registry_http",
        "examples/sample-registry-http/app.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def empty_registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    (root / "packs").mkdir(parents=True)
    (root / "publishers").mkdir(parents=True)
    write_index(root)
    return root


@pytest.fixture
def app_factory(empty_registry: Path):
    module = _load_fastapi_module()

    def make(**overrides) -> TestClient:
        config = ServerConfig(registry_root=empty_registry, **overrides)
        server = RegistryServer(config)
        app = module.create_app(server)
        return TestClient(app)

    return make


class _TestClientHttpsRegistry(HttpsRegistry):
    """HttpsRegistry that dispatches reads + writes through a TestClient."""

    def __init__(self, client: TestClient, **kwargs: object) -> None:
        super().__init__("https://test.invalid", **kwargs)
        self._client = client

    def _http_get(self, url: str) -> bytes:
        path = url[len(self._base) :] or "/"
        response = self._client.get(path)
        if response.status_code != 200:
            from kb_registry import RegistryError

            raise RegistryError(
                f"HTTPS fetch failed for {url!r}: HTTP {response.status_code}"
            )
        if len(response.content) > self._max_bytes:
            from kb_registry import RegistryError

            raise RegistryError(
                f"response for {url!r} exceeded {self._max_bytes} bytes"
            )
        return response.content

    def _http_submit(
        self,
        url: str,
        *,
        tar_bytes: bytes,
        filename: str,
        notes: str,
        bearer_token: str | None,
    ) -> dict:
        path = url[len(self._base) :]
        headers = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        files = {"tarball": (filename, tar_bytes, "application/x-tar")}
        data = {"notes": notes} if notes else {}
        response = self._client.post(path, files=files, data=data, headers=headers)
        return response.json()


def test_http_submit_round_trip_publish_fetch_verify(
    tmp_path: Path, empty_registry: Path, app_factory
) -> None:
    from tests.test_registry_submit import _build_pack, _install_publisher_keys

    publisher_id = "did:web:bob.example"
    tar_path = _build_pack(tmp_path, "http.roundtrip", "1.0.0", publisher_id)
    kb_root = tar_path.parents[1]
    _install_publisher_keys(empty_registry, publisher_id, kb_root)

    client = app_factory()
    reg = _TestClientHttpsRegistry(client)

    response = reg.submit(tar_path)
    assert response["accepted"], response

    # Re-read index over HTTP; the new version is discoverable.
    resolved = reg.resolve("http.roundtrip", "^1.0")
    assert resolved.version == "1.0.0"

    # Fetch + extract through the same HTTP transport.
    extracted = reg.fetch("http.roundtrip", "1.0.0", tmp_path / "consumer-install")
    assert (extracted / "pack.manifest.yaml").is_file()
    assert (extracted / "signatures" / "publisher.sig").is_file()


def test_http_submit_rejects_bad_pack_with_structured_errors(
    tmp_path: Path, empty_registry: Path, app_factory
) -> None:
    # No publisher keys installed — submit should return 400 with errors[].
    from tests.test_registry_submit import _build_pack

    tar_path = _build_pack(tmp_path, "ghost.http", "1.0.0", "did:web:ghost.example")
    client = app_factory()
    reg = _TestClientHttpsRegistry(client)

    # Go through raw HTTP to assert the status code AND body shape.
    with tar_path.open("rb") as fh:
        response = client.post(
            "/v0.1/submit",
            files={"tarball": ("ghost.tar", fh, "application/x-tar")},
        )
    assert response.status_code == 400
    body = response.json()
    assert body["accepted"] is False
    assert body["errors"][0]["check"] == "publisher_keys_known"


def test_http_private_tier_requires_bearer(
    tmp_path: Path, empty_registry: Path, app_factory
) -> None:
    from tests.test_registry_submit import _build_pack, _install_publisher_keys

    publisher_id = "did:web:private.example"
    tar_path = _build_pack(tmp_path, "private.pack", "1.0.0", publisher_id)
    kb_root = tar_path.parents[1]
    _install_publisher_keys(empty_registry, publisher_id, kb_root)

    client = app_factory(
        trust_role="private",
        bearer_tokens=frozenset({"letmein"}),
    )

    # No token → 400 bearer_token.
    reg = _TestClientHttpsRegistry(client)
    without = reg.submit(tar_path)
    assert without["accepted"] is False
    assert without["errors"][0]["check"] == "bearer_token"

    # With token → accepted.
    with_token = reg.submit(tar_path, bearer_token="letmein")
    assert with_token["accepted"] is True


def test_http_endpoints_reject_unsafe_path_components(app_factory) -> None:
    client = app_factory()
    assert client.get("/packs/..%2F..%2Fetc/passwd").status_code == 404
    # FastAPI normalizes; ".." directly in a path component is a 400.
    assert client.get("/publishers/..%2Ffoo/keys.json").status_code in (400, 404)


def test_http_health_endpoint(app_factory) -> None:
    client = app_factory()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": "true"}


def test_http_index_404_when_missing(app_factory, empty_registry: Path) -> None:
    (empty_registry / "index.json").unlink()
    client = app_factory()
    assert client.get("/index.json").status_code == 404
