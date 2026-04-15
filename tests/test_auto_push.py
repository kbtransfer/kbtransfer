"""publisher.auto_push: kb/publish/0.1 chirps the signed tarball to
every URL listed under policy.publisher.auto_push after a successful
local publish. Explicit submit_to_registry argument takes precedence
and suppresses auto-push to avoid a double-push."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kb_cli.init import scaffold
from kb_mcp_server.tools import HANDLERS
from kb_registry import HttpsRegistry, write_index
from kb_registry_server import RegistryServer, ServerConfig


def _call(root: Path, name: str, args: dict) -> dict:
    return json.loads(asyncio.run(HANDLERS[name](root, args))[0].text)


def _load_fastapi_module():
    spec = importlib.util.spec_from_file_location(
        "kbtransfer_sample_registry_http_ap",
        "examples/sample-registry-http/app.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_registry(tmp_path: Path, label: str) -> Path:
    root = tmp_path / f"reg-{label}"
    (root / "packs").mkdir(parents=True)
    (root / "publishers").mkdir(parents=True)
    write_index(root)
    return root


def _install_pub_keys(registry_root: Path, kb_root: Path, publisher_id: str) -> None:
    did_safe = publisher_id.replace(":", "-")
    pub_dir = registry_root / "publishers" / did_safe
    pub_dir.mkdir(parents=True, exist_ok=True)
    pub_key_file = next((kb_root / ".kb" / "keys").glob("*.pub"))
    pub_doc = yaml.safe_load(pub_key_file.read_text())
    (pub_dir / "keys.json").write_text(
        json.dumps(
            {
                "publisher_id": publisher_id,
                "display_name": "Auto-push KB",
                "keys": [
                    {
                        "key_id": pub_doc["key_id"],
                        "algorithm": "ed25519",
                        "public_key_hex": pub_doc["public_key_hex"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _patch_open_registry_to_use(monkeypatch, clients: dict[str, TestClient]) -> None:
    import kb_registry

    real_open = kb_registry.open_registry

    class _ClientHttpsRegistry(HttpsRegistry):
        def __init__(self, url: str, client: TestClient) -> None:
            super().__init__(url)
            self._client = client

        def _http_get(self, url: str) -> bytes:
            path = url[len(self._base) :] or "/"
            r = self._client.get(path)
            if r.status_code != 200:
                from kb_registry import RegistryError

                raise RegistryError(f"HTTPS fetch failed for {url!r}: HTTP {r.status_code}")
            return r.content

        def _http_submit(self, url, *, tar_bytes, filename, notes, bearer_token):
            path = url[len(self._base) :]
            headers = {}
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            files = {"tarball": (filename, tar_bytes, "application/x-tar")}
            data = {"notes": notes} if notes else {}
            r = self._client.post(path, files=files, data=data, headers=headers)
            return r.json()

    def fake_open(url: str):
        for key, client in clients.items():
            if url.startswith(key):
                return _ClientHttpsRegistry(url, client)
        return real_open(url)

    # Patch at both module and call site: publish.py imports inside
    # _submit_to_registry.
    monkeypatch.setattr(kb_registry, "open_registry", fake_open)


def _publish_pack(
    kb_root: Path, pack_id: str, version: str, extra_args: dict | None = None
) -> dict:
    (kb_root / "wiki" / "patterns").mkdir(parents=True, exist_ok=True)
    (kb_root / "wiki" / "patterns" / "p.md").write_text(
        f"# {pack_id}\n\nBody {version}.\n", encoding="utf-8"
    )
    draft = _call(
        kb_root,
        "kb/draft_pack/0.1",
        {
            "pack_id": pack_id,
            "version": version,
            "title": pack_id,
            "summary": "auto-push fixture.",
            "source_pages": ["wiki/patterns/p.md"],
        },
    )
    assert draft["ok"], draft
    _call(kb_root, "kb/distill/0.1", {"pack_id": pack_id})
    args = {"pack_id": pack_id}
    args.update(extra_args or {})
    return _call(kb_root, "kb/publish/0.1", args)


def _set_auto_push(kb_root: Path, urls: list[str]) -> None:
    policy_path = kb_root / ".kb" / "policy.yaml"
    doc = yaml.safe_load(policy_path.read_text())
    doc.setdefault("publisher", {})["auto_push"] = urls
    policy_path.write_text(yaml.safe_dump(doc, sort_keys=False))


def test_auto_push_fans_out_to_every_registry(tmp_path: Path, monkeypatch) -> None:
    kb_root = tmp_path / "kb"
    scaffold(root=kb_root, tier="individual", publisher_id="did:web:ap.example")

    reg_a = _make_registry(tmp_path, "a")
    reg_b = _make_registry(tmp_path, "b")
    _install_pub_keys(reg_a, kb_root, "did:web:ap.example")
    _install_pub_keys(reg_b, kb_root, "did:web:ap.example")

    module = _load_fastapi_module()
    client_a = TestClient(module.create_app(RegistryServer(ServerConfig(registry_root=reg_a))))
    client_b = TestClient(module.create_app(RegistryServer(ServerConfig(registry_root=reg_b))))
    _patch_open_registry_to_use(
        monkeypatch,
        {"https://reg-a.invalid": client_a, "https://reg-b.invalid": client_b},
    )

    _set_auto_push(kb_root, ["https://reg-a.invalid", "https://reg-b.invalid"])

    published = _publish_pack(kb_root, "ap.pack", "1.0.0")
    assert published["ok"], published
    subs = published["data"]["submissions"]
    assert len(subs) == 2
    assert all(s["ok"] for s in subs), subs
    assert (reg_a / "packs" / "ap.pack" / "1.0.0.tar").is_file()
    assert (reg_b / "packs" / "ap.pack" / "1.0.0.tar").is_file()


def test_explicit_submit_wins_over_auto_push(tmp_path: Path, monkeypatch) -> None:
    kb_root = tmp_path / "kb2"
    scaffold(root=kb_root, tier="individual", publisher_id="did:web:override.example")

    reg_default = _make_registry(tmp_path, "default")
    reg_override = _make_registry(tmp_path, "override")
    _install_pub_keys(reg_default, kb_root, "did:web:override.example")
    _install_pub_keys(reg_override, kb_root, "did:web:override.example")

    module = _load_fastapi_module()
    client_default = TestClient(
        module.create_app(RegistryServer(ServerConfig(registry_root=reg_default)))
    )
    client_override = TestClient(
        module.create_app(RegistryServer(ServerConfig(registry_root=reg_override)))
    )
    _patch_open_registry_to_use(
        monkeypatch,
        {
            "https://reg-default.invalid": client_default,
            "https://reg-override.invalid": client_override,
        },
    )

    _set_auto_push(kb_root, ["https://reg-default.invalid"])
    published = _publish_pack(
        kb_root,
        "override.pack",
        "1.0.0",
        {"submit_to_registry": "https://reg-override.invalid"},
    )
    assert published["ok"], published
    # Explicit submit path populated.
    assert "submission" in published["data"]
    assert published["data"]["submission"]["ok"]
    # Auto-push fan-out suppressed.
    assert "submissions" not in published["data"]
    # Override registry got the pack; default did not.
    assert (reg_override / "packs" / "override.pack" / "1.0.0.tar").is_file()
    assert not (reg_default / "packs" / "override.pack" / "1.0.0.tar").exists()


def test_auto_push_continues_on_per_registry_failure(
    tmp_path: Path, monkeypatch
) -> None:
    kb_root = tmp_path / "kb3"
    scaffold(root=kb_root, tier="individual", publisher_id="did:web:mixed.example")

    reg_good = _make_registry(tmp_path, "good")
    _install_pub_keys(reg_good, kb_root, "did:web:mixed.example")
    # reg_broken: missing publisher keys → submit will be rejected with
    # publisher_keys_known. Verify that the loop does NOT abort and still
    # pushes to reg_good.
    reg_broken = _make_registry(tmp_path, "broken")

    module = _load_fastapi_module()
    client_good = TestClient(module.create_app(RegistryServer(ServerConfig(registry_root=reg_good))))
    client_broken = TestClient(
        module.create_app(RegistryServer(ServerConfig(registry_root=reg_broken)))
    )
    _patch_open_registry_to_use(
        monkeypatch,
        {
            "https://reg-good.invalid": client_good,
            "https://reg-broken.invalid": client_broken,
        },
    )

    _set_auto_push(
        kb_root, ["https://reg-broken.invalid", "https://reg-good.invalid"]
    )
    published = _publish_pack(kb_root, "mixed.pack", "1.0.0")
    assert published["ok"], published

    subs = published["data"]["submissions"]
    assert len(subs) == 2
    assert subs[0]["ok"] is False
    assert subs[0]["error_code"] == "registry_rejected"
    assert subs[1]["ok"] is True
    # Good registry got the pack; broken did not.
    assert (reg_good / "packs" / "mixed.pack" / "1.0.0.tar").is_file()
    assert not (reg_broken / "packs" / "mixed.pack" / "1.0.0.tar").exists()
