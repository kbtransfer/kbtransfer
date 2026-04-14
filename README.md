# KBTRANSFER

**An open protocol + reference implementation for a local-first,
federated knowledge base between AI agents.**

Users keep their own Karpathy-style markdown wiki. Their agents both
contribute to it (ingest sources, write patterns, log decisions and
failures) and consume verified knowledge packs distilled from other
users' wikis. Sharing is cryptographically signed, verifiable offline,
and distributed through a git-based registry.

**Status:** Planning locked 2026-04-14. Implementation in progress.
See [`ROADMAP.md`](./ROADMAP.md) for phased delivery.

---

## Why it exists

Two patterns already solve half the problem each. Neither bridges to
the other.

- **Karpathy's LLM Wiki** (intra-agent): an LLM maintains a living
  markdown wiki that compounds over time instead of rediscovering
  knowledge per query.
  [Original gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

- **AutoEvolve Packs** (inter-agent): pattern-level knowledge packs,
  Ed25519-signed, four-attestation, redacted by a bias-isolated
  pipeline, verifiable offline. Specs live under
  [`specs/current/`](./specs/current/); dogfood iteration history under
  [`reports/`](./reports/).

KBTRANSFER is the missing bridge: the live wiki where knowledge grows,
the distillation pipeline that turns a slice of that wiki into a
shareable pack, and the consumption layer that imports other people's
packs without polluting your own wiki.

## What makes it different

**Experience is first-class.** The default wiki skeleton reserves two
dedicated folders, `decisions/` and `failure-log/`, alongside the
usual `patterns/` and `entities/`. Raw reference docs can be
rediscovered from public sources; what a team actually tried,
what broke, and why they chose X over Y cannot. These experience pages
are the pages that distill into the most valuable packs.

**One protocol, three tiers.** Individual developers, small teams, and
regulated enterprises share the same pack format but scale redaction
strictness, trust posture, and review gates to match their compliance
needs. A single `.kb/tier.yaml` drives every tier-dependent behavior.

**MCP-native.** The reference implementation ships as an MCP server,
so Claude Code, Cursor, Claude Desktop, and any MCP-aware agent can
drive it without a custom adapter.

**Plain markdown + git.** User data is a folder of markdown files
tracked by git. No database owns the truth. A git clone is a complete
backup; a git diff is a complete audit trail.

## Repository map

| Path | What's there |
|------|--------------|
| [`ROADMAP.md`](./ROADMAP.md) | Phased v1 delivery plan |
| [`specs/current/`](./specs/current/) | Authoritative pack + registry specs |
| [`reports/`](./reports/) | Three dogfood iteration reports |
| `reference/` | Python reference implementation (Phase 1 onward) |
| `tests/` | Adversarial + integration test suites |
| `examples/` | Sample KB templates |
| [`LICENSE.md`](./LICENSE.md) | Dual-licensing details |

## Licenses

- Code (`reference/`, `tests/`, `examples/`): Apache License 2.0.
- Specs and reports: CC BY-SA 4.0.

See [`LICENSE.md`](./LICENSE.md) for details.

## Attribution

Built on top of the AutoEvolve Packs specification and the LLM-Wiki
pattern from Andrej Karpathy. Full background in
[`specs/current/autoevolve-packs-overview.md`](./specs/current/autoevolve-packs-overview.md).
