"""`python -m kb_mcp_server` entry point; also invoked as `kb-mcp`.

Accepts a single optional `--root` flag; otherwise the server resolves
the KB root from the `KB_ROOT` environment variable or the current
working directory. See kb_mcp_server.kb_root for details.
"""

from __future__ import annotations

import argparse
import logging
import sys

from kb_mcp_server.kb_root import KBRootError
from kb_mcp_server.server import serve


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kb-mcp", description="KBTRANSFER MCP server")
    parser.add_argument(
        "--root",
        default=None,
        help="Path to the KB root (containing .kb/). Overrides KB_ROOT env var.",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))
    try:
        serve(args.root)
    except KBRootError as exc:
        print(f"kb-mcp: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
