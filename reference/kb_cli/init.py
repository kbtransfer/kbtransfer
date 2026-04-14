"""`kb init` command: scaffold a fresh KB directory."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from importlib.resources import files as resource_files
from pathlib import Path
from typing import Literal

import click
import yaml

from kb_cli.keygen import generate_keypair, write_keypair

Tier = Literal["individual", "team", "enterprise"]

REQUIRED_WIKI_FOLDERS = ("patterns", "decisions", "failure-log", "entities")
RUNTIME_FOLDERS = ("sources", "subscriptions", "drafts", "published")


def _templates_root() -> Path:
    return Path(str(resource_files("kb_cli").joinpath("templates")))


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _write_tier_yaml(kb_dir: Path, tier: Tier, publisher_id: str, key_id: str) -> None:
    doc = {
        "tier_version": "kbtransfer/0.1",
        "tier": tier,
        "publisher_id": publisher_id,
        "signing_key_id": key_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    (kb_dir / "tier.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8"
    )


def _install_policy(kb_dir: Path, templates: Path, tier: Tier) -> None:
    source = templates / "kb" / "policy" / f"{tier}.yaml"
    shutil.copyfile(source, kb_dir / "policy.yaml")


def _install_static_kb_files(kb_dir: Path, templates: Path) -> None:
    shutil.copyfile(templates / "kb" / "schema.yaml", kb_dir / "schema.yaml")
    shutil.copyfile(templates / "kb" / "trust-store.yaml", kb_dir / "trust-store.yaml")


def _install_wiki(root: Path, templates: Path) -> None:
    _copy_tree(templates / "wiki", root / "wiki")


def _create_runtime_folders(root: Path) -> None:
    for folder in RUNTIME_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
        gitkeep = root / folder / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")


def _kb_is_nonempty(root: Path) -> bool:
    return (root / ".kb").exists() or (root / "wiki").exists()


def scaffold(
    root: Path,
    tier: Tier,
    publisher_id: str,
    generate_keys: bool = True,
    force: bool = False,
) -> dict[str, Path]:
    """Scaffold a KB under `root`. Returns a map of interesting paths."""
    root = root.expanduser().resolve()
    if _kb_is_nonempty(root) and not force:
        raise click.ClickException(
            f"{root} already contains a KB (use --force to overwrite)."
        )

    templates = _templates_root()
    kb_dir = root / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)

    _install_static_kb_files(kb_dir, templates)
    _install_policy(kb_dir, templates, tier)
    _install_wiki(root, templates)
    _create_runtime_folders(root)

    key_id = ""
    if generate_keys:
        keypair = generate_keypair(publisher_id=publisher_id)
        write_keypair(kb_dir / "keys", keypair)
        key_id = keypair.key_id
    _write_tier_yaml(kb_dir, tier, publisher_id, key_id)

    return {
        "root": root,
        "kb_dir": kb_dir,
        "wiki_dir": root / "wiki",
    }


@click.command("init", help="Scaffold a fresh KBTRANSFER knowledge base at PATH.")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("."),
)
@click.option(
    "--tier",
    type=click.Choice(["individual", "team", "enterprise"]),
    default="individual",
    show_default=True,
    help="Tier policy to install (drives trust model, redaction level, review gates).",
)
@click.option(
    "--publisher-id",
    default="did:web:example.invalid",
    show_default=True,
    help="DID-style publisher identifier for signed packs this KB will produce.",
)
@click.option(
    "--no-keygen",
    is_flag=True,
    help="Skip Ed25519 keypair generation. Useful for shared/read-only KBs.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing KB at PATH.",
)
def init_command(
    path: Path,
    tier: Tier,
    publisher_id: str,
    no_keygen: bool,
    force: bool,
) -> None:
    result = scaffold(
        root=path,
        tier=tier,
        publisher_id=publisher_id,
        generate_keys=not no_keygen,
        force=force,
    )
    click.echo(f"Initialized {tier}-tier KB at {result['root']}")
    click.echo(f"  .kb/        {result['kb_dir']}")
    click.echo(f"  wiki/       {result['wiki_dir']}")
    if not no_keygen:
        click.echo(f"  .kb/keys/   Ed25519 keypair for {publisher_id}")
    click.echo("Next: `kb doctor` to verify, then drop sources under sources/.")
