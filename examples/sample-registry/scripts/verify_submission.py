#!/usr/bin/env python3
"""Pre-merge verification for a kb-registry PR.

Discovers every pack tarball under `packs/` (or a subset passed on
the command line), extracts each into a temp directory, and runs the
reference verifier against the publisher keys recorded under
`publishers/<did-safe>/keys.json`. Exits non-zero if any pack fails.

Intended to be invoked by GitHub Actions on pull_request; see
`.github/workflows/verify-pack.yml` for the wiring.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

try:
    from kb_pack import PublisherKeyResolver, load_manifest, verify_pack
except ImportError as exc:
    sys.stderr.write(
        "kb_pack is not installed. Run `pip install -e .` from the "
        "KBTRANSFER repo root before invoking this script.\n"
    )
    raise SystemExit(1) from exc


def _extract(tar_path: Path, dest: Path) -> Path:
    with tarfile.open(tar_path, "r") as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)
    entries = [p for p in dest.iterdir() if p.is_dir()]
    if len(entries) != 1:
        raise RuntimeError(
            f"tarball {tar_path} did not contain a single top-level directory"
        )
    return entries[0]


def _resolver_from_publishers_dir(publishers_dir: Path) -> PublisherKeyResolver:
    resolver = PublisherKeyResolver()
    if not publishers_dir.is_dir():
        return resolver
    for publisher_dir in sorted(publishers_dir.iterdir()):
        keys_json = publisher_dir / "keys.json"
        if not keys_json.is_file():
            continue
        try:
            doc = json.loads(keys_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        publisher_id = doc.get("publisher_id", "")
        for key in doc.get("keys") or []:
            if key.get("algorithm") != "ed25519":
                continue
            key_id = key.get("key_id")
            hex_val = key.get("public_key_hex")
            if key_id and hex_val and publisher_id:
                resolver.register(publisher_id, key_id, hex_val)
    return resolver


def _verify_tarball(tar_path: Path, resolver: PublisherKeyResolver) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        extracted = _extract(tar_path, Path(tmp))
        manifest = load_manifest(extracted)
        result = verify_pack(extracted, resolver)
        if result.ok:
            return True, f"OK {manifest.pack_ref} ({tar_path.name})"
        return (
            False,
            f"FAIL [{result.step}] {manifest.pack_ref}: {result.message} "
            f"({tar_path.name})",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-merge kb-registry verification.")
    parser.add_argument(
        "registry_root",
        type=Path,
        help="Path to the registry root (the directory containing publishers/ and packs/).",
    )
    parser.add_argument(
        "--pack",
        dest="packs",
        type=Path,
        action="append",
        help="Only verify these tarball paths (relative to registry_root). "
        "Repeat to verify multiple. Defaults to every tarball under packs/.",
    )
    args = parser.parse_args(argv)

    registry_root = args.registry_root.resolve()
    if not registry_root.is_dir():
        print(f"registry root not found: {registry_root}", file=sys.stderr)
        return 2

    resolver = _resolver_from_publishers_dir(registry_root / "publishers")

    targets: list[Path]
    if args.packs:
        targets = [registry_root / p for p in args.packs]
    else:
        targets = sorted((registry_root / "packs").rglob("*.tar"))
    if not targets:
        print("No pack tarballs found to verify.")
        return 0

    failures = 0
    for tar_path in targets:
        if not tar_path.is_file():
            print(f"SKIP {tar_path} (not a file)")
            continue
        try:
            ok, message = _verify_tarball(tar_path, resolver)
        except Exception as exc:
            ok, message = False, f"FAIL [exception] {tar_path.name}: {exc}"
        print(message)
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} pack(s) failed verification.")
        return 1
    print(f"\nAll {len(targets)} pack(s) verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
