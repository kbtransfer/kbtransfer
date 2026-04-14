"""KB root discovery for the MCP server.

Resolution order:
    1. Explicit `--root` flag passed to the server.
    2. `KB_ROOT` environment variable.
    3. Current working directory (if it contains a `.kb/` directory).

The server refuses to start if none of these yield a valid KB. Tools,
once running, trust the resolved root for the lifetime of the process.
"""

from __future__ import annotations

import os
from pathlib import Path


class KBRootError(RuntimeError):
    pass


def resolve_kb_root(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env_value = os.environ.get("KB_ROOT")
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(Path.cwd())

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / ".kb").is_dir():
            return resolved

    raise KBRootError(
        "No KB root found. Pass --root, set KB_ROOT, or cd into a directory "
        "produced by `kb init`."
    )
