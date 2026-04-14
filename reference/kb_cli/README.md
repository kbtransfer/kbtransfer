# kb_cli

Command-line entry point for KBTRANSFER.

## Commands (Phase 1)

| Command     | What it does                                              |
|-------------|-----------------------------------------------------------|
| `kb init`   | Scaffold a fresh KB directory with tier-aware defaults    |
| `kb doctor` | Check the current KB for missing config, keys, or skeleton |
| `kb lint`   | Run schema lint rules across the wiki (health check)       |

## Running

Install the project (from the repo root) with `pip install -e .[dev]`.
Then:

```bash
kb --help
kb init my-kb --tier individual
kb doctor --path my-kb
```

`kb` is a thin dispatcher; the heavy lifting lives in
`kb_mcp_server`, `kb_pack`, and `kb_distiller`.
