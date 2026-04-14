"""Command group for the `kb` CLI."""

from __future__ import annotations

from pathlib import Path

import click

from kb_cli import __version__
from kb_cli.init import init_command


@click.group(
    help="KBTRANSFER command-line interface. Run `kb init` to scaffold a new KB.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="kb")
def cli() -> None:
    pass


cli.add_command(init_command)


@cli.command(help="Print diagnostic information about the current KB and environment.")
@click.option(
    "--path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path.cwd(),
    help="KB root to inspect (defaults to current working directory).",
)
def doctor(path: Path) -> None:
    kb_dir = path / ".kb"
    if not kb_dir.is_dir():
        click.echo(f"No .kb/ found under {path}.", err=True)
        click.echo("Run `kb init <path>` to create one.", err=True)
        raise SystemExit(1)
    click.echo(f"KB root: {path}")
    click.echo(f"Config:  {kb_dir}")
    for name in ("tier.yaml", "policy.yaml", "schema.yaml", "trust-store.yaml"):
        marker = "OK" if (kb_dir / name).is_file() else "MISSING"
        click.echo(f"  .kb/{name:<18} {marker}")
    keys_dir = kb_dir / "keys"
    key_count = sum(1 for _ in keys_dir.glob("*.pub")) if keys_dir.is_dir() else 0
    click.echo(f"  .kb/keys/            {key_count} public key(s)")


if __name__ == "__main__":
    cli()
