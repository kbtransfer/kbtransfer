# kb_mcp_server

Stdio MCP server exposing the `kb/*` tool surface to any MCP-aware
agent (Claude Code, Cursor, Claude Desktop, custom).

## Phase 1 tools

| Tool                      | Purpose                                            |
|---------------------------|----------------------------------------------------|
| `kb/search/0.1`           | Text search across wiki/ and subscriptions/        |
| `kb/read/0.1`             | Read a page under wiki/, subscriptions/, sources/, or drafts/ |
| `kb/write/0.1`            | Create or overwrite a page under wiki/, drafts/, or sources/ |
| `kb/ingest_source/0.1`    | Save a source and return a reading plan (Karpathy flow) |
| `kb/lint/0.1`             | Schema-driven health check                         |
| `kb/policy_get/0.1`       | Return the current .kb/policy.yaml                 |
| `kb/policy_set/0.1`       | Update a single leaf in .kb/policy.yaml            |

Every tool returns a uniform envelope:

```json
{"ok": true,  "data": {...}, "error": null}
{"ok": false, "data": null,  "error": {"code": "...", "message": "..."}}
```

## Running

```bash
# Explicit root
kb-mcp --root /path/to/my-kb

# Or from inside the KB
cd my-kb && kb-mcp

# Or via env var
KB_ROOT=/path/to/my-kb kb-mcp
```

The server speaks MCP over stdio. Configure your agent's MCP client
to launch this command; no network sockets are opened.

## Adding a new tool

1. Create `reference/kb_mcp_server/tools/<name>.py` exposing `TOOL`
   (an `mcp.types.Tool`) and `HANDLER` (an async callable).
2. Add the module to `_MODULES` in `tools/__init__.py`.
3. Write tests under `tests/test_mcp_<name>.py`.

Tool names MUST include a version suffix (`/0.1`). Breaking changes
ship a new suffix until the old one is removed.
