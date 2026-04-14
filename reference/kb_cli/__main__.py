"""`python -m kb_cli` entry point; also invoked as the `kb` console script."""

from __future__ import annotations

from kb_cli.cli import cli


def main() -> int:
    cli()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
