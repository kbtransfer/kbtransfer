# `kb-distill` skill

A Claude Code [skill](https://docs.claude.com/en/docs/claude-code/skills)
that drives the **single-model team-tier** distillation pipeline of
KBTRANSFER through a real LLM pass — turning the checklist that
`kb/distill/0.1` emits into actual paraphrase + redaction edits, then
stamping the resulting `.distill-report.json` so `kb/publish/0.1`
records LLM provenance in the redaction attestation.

This is the **3.a** deliverable from the v2 distiller skill plan. The
**3.b** dual-model adversarial variant (with a different-family
verifier model) is a separate skill, not yet shipped.

## Install

```bash
# 1. Have KBTRANSFER installed and the kb-mcp server registered:
pip install -e /path/to/KBTRANSFER
claude mcp add kb-mcp kb-mcp

# 2. Copy this skill into your global Claude Code skills directory:
cp -r examples/skills/kb-distill ~/.claude/skills/

# 3. Verify it loads:
#    Open Claude Code, type "/" — kb-distill should appear in the
#    skill list.
```

## Use

Inside Claude Code, with a draft pack at `drafts/<pack_id>/`:

```
/kb-distill <pack_id>
```

The skill will:

1. Run `kb/distill/0.1` to baseline.
2. Loop kb/read → LLM paraphrase → kb/write until the regex scrubber
   returns zero findings (max 3 iterations).
3. Run a single residual-review pass for soft signals (client names,
   codenames, monetary amounts, stylometric leaks).
4. Stamp `drafts/<pack_id>/.distill-report.json` with an
   `llm_assisted_by` block recording model, iteration count, and
   completion timestamps.
5. Hand back to you with a short summary; **does not** auto-publish.

You then decide whether to call `kb/publish/0.1`.

## What this skill is NOT

- **Not for individual tier.** The `manual` mode runs the regex
  scrubber alone and emits a checklist for human review. No skill
  needed; just call `kb/distill/0.1` directly.
- **Not for enterprise tier.** `dual-model` mode requires a verifier
  model from a different family running adversarially against the
  redactor's output (spec §10 + design decision 4/C from 2026-04-15).
  That is a separate skill currently under design as `kb-distill-adversarial`.
- **Not a substitute for human review** when stakes are high.
  Single-model paraphrase is good at structured PII and obvious soft
  signals; it can miss subtle context leaks that a domain expert
  would catch. The `residual_risk_notes` field is honest about this
  by design.

## Provenance recorded in the attestation

When `kb/publish/0.1` is later called, the redaction attestation will
carry an `llm_assisted_by` block:

```json
{
  "redaction_level": "standard",
  "policy_applied": "kbtransfer-single-model",
  "categories_redacted": ["identity.person.email", "client.organization", ...],
  "residual_risk_notes": [
    "Regex scrubber handles only well-formed PII patterns ...",
    "Stylometric fingerprints from the original author survive paraphrase passes."
  ],
  "llm_assisted_by": {
    "model": "claude-opus-4-6",
    "mode": "single-model",
    "skill": "kb-distill@0.1",
    "regex_loop_iterations": 2,
    "residual_review_pass2": true,
    "started_at": "2026-04-15T13:42:00Z",
    "completed_at": "2026-04-15T13:42:47Z",
    "pages_rewritten": 4
  },
  "signature": { "..." }
}
```

Downstream consumers can weigh the attestation knowing an LLM rewrote
the content. Combined with RFC-0004 timestamping (Phase 5) and
RFC-0006 revocation (Phase 6), this becomes part of the v2 trust
story: not just "what was redacted" but "by whom, when, and how."

## See also

- `reference/kb_distiller/pipeline.py` — tier → mode mapping; the
  checklist this skill executes.
- `reference/kb_distiller/scrubber.py` — the deterministic regex
  layer, including the `ScrubFinding` location fields this skill
  consumes.
- `reports/skill-3a-distiller-single-model.md` — dogfood report for
  this skill, including residual risks and what 3.b will add.
