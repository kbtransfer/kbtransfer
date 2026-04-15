"""FastAPI front for a KBTRANSFER registry.

Wraps `kb_registry_server.RegistryServer` for validation + storage and
exposes the read paths `HttpsRegistry` expects (`/index.json`,
`/packs/...`, `/publishers/...`) plus the RFC-0002 write endpoint
`POST /v0.1/submit`.

Environment variables:

    KBTRANSFER_REGISTRY_ROOT   required — path to the registry layout root.
    KBTRANSFER_TRUST_ROLE      open | consortium | private (default: open).
    KBTRANSFER_COMMIT_MODE     auto | stage (default: auto).
    KBTRANSFER_ALLOWLIST       comma-separated publisher DIDs (consortium).
    KBTRANSFER_BEARER_TOKENS   comma-separated tokens (private).
    KBTRANSFER_MAX_BYTES       submission size cap (default: 256 MiB).
    KBTRANSFER_REGISTRY_ID     did:web: of the registry (optional).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from kb_registry_server import RegistryServer, ServerConfig


def _env_frozenset(name: str) -> frozenset[str]:
    raw = os.environ.get(name, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def build_server(root: Path | None = None) -> RegistryServer:
    registry_root = root or Path(
        os.environ.get("KBTRANSFER_REGISTRY_ROOT", "")
    ).expanduser().resolve()
    if not registry_root or not registry_root.is_dir():
        raise RuntimeError(
            f"KBTRANSFER_REGISTRY_ROOT must point at an existing directory "
            f"(got {registry_root!r})"
        )
    config = ServerConfig(
        registry_root=registry_root,
        trust_role=os.environ.get("KBTRANSFER_TRUST_ROLE", "open"),
        commit_mode=os.environ.get("KBTRANSFER_COMMIT_MODE", "auto"),
        allowlist=_env_frozenset("KBTRANSFER_ALLOWLIST"),
        bearer_tokens=_env_frozenset("KBTRANSFER_BEARER_TOKENS"),
        max_bytes=int(os.environ.get("KBTRANSFER_MAX_BYTES", str(256 * 1024 * 1024))),
        registry_id=os.environ.get("KBTRANSFER_REGISTRY_ID", ""),
    )
    return RegistryServer(config)


def create_app(server: RegistryServer | None = None) -> FastAPI:
    app = FastAPI(
        title="KBTRANSFER sample registry",
        version="0.1.0",
        description="Reference HTTP front for a KBTRANSFER kb-registry (RFC-0002).",
    )
    if server is None:
        server = build_server()
    app.state.server = server

    def get_server() -> RegistryServer:
        return app.state.server

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/index.json")
    def index(srv: RegistryServer = Depends(get_server)) -> FileResponse:
        target = srv.registry_root / "index.json"
        if not target.is_file():
            raise HTTPException(status_code=404, detail="index.json not built yet")
        return FileResponse(target, media_type="application/json")

    @app.get("/packs/{pack_id}/{filename}")
    def fetch_pack(
        pack_id: str,
        filename: str,
        srv: RegistryServer = Depends(get_server),
    ) -> FileResponse:
        _reject_path_components(pack_id, filename)
        target = srv.registry_root / "packs" / pack_id / filename
        if not target.is_file():
            raise HTTPException(status_code=404, detail="tarball not found")
        return FileResponse(target, media_type="application/x-tar")

    @app.get("/publishers/{did_safe}/keys.json")
    def publisher_keys(
        did_safe: str,
        srv: RegistryServer = Depends(get_server),
    ) -> FileResponse:
        _reject_path_components(did_safe)
        target = srv.registry_root / "publishers" / did_safe / "keys.json"
        if not target.is_file():
            raise HTTPException(status_code=404, detail="publisher not registered")
        return FileResponse(target, media_type="application/json")

    @app.post("/v0.1/submit")
    async def submit(
        tarball: UploadFile = File(...),
        notes: str = Form(""),
        authorization: str | None = Header(default=None),
        srv: RegistryServer = Depends(get_server),
    ) -> JSONResponse:
        body = await tarball.read()
        bearer = _extract_bearer(authorization)
        result = srv.submit(body, bearer_token=bearer, notes=notes)
        status = 200 if result.accepted else 400
        return JSONResponse(status_code=status, content=result.to_wire())

    return app


def _reject_path_components(*parts: str) -> None:
    for part in parts:
        if "/" in part or ".." in part or part.startswith("."):
            raise HTTPException(status_code=400, detail=f"unsafe path part: {part!r}")


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip() or None


app = create_app() if os.environ.get("KBTRANSFER_REGISTRY_ROOT") else None
