"""Filesystem helpers for the subscriptions/ tree.

Subscribed packs are installed with read-only permissions (files
0o444, directories 0o555) so an unrelated tool cannot silently mutate
verified content. `make_tree_writable` restores write bits in the
two scenarios that need to replace or remove the tree: re-subscribe
and unsubscribe.
"""

from __future__ import annotations

import os
from pathlib import Path


def make_tree_read_only(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(Path(dirpath) / name, 0o444)
        for name in dirnames:
            os.chmod(Path(dirpath) / name, 0o555)
    os.chmod(root, 0o555)


def make_tree_writable(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root):
        try:
            os.chmod(dirpath, 0o755)
        except OSError:
            pass
        for name in filenames:
            try:
                os.chmod(Path(dirpath) / name, 0o644)
            except OSError:
                pass
    try:
        os.chmod(root, 0o755)
    except OSError:
        pass


__all__ = ["make_tree_read_only", "make_tree_writable"]
