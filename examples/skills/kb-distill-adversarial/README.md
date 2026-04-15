# `kb-distill-adversarial` skill

The **dual-model enterprise-tier** distillation skill for
KBTRANSFER. Wraps the single-model
[`kb-distill`](../kb-distill/README.md) loop with an adversarial
verifier sub-call: after redaction, a verifier model from a
different family probes each rewritten page for canary recovery, and
any successful recovery loops back into Pass-2 with a stricter
prompt.

This is the **3.b** deliverable from the v2 distiller skill plan
(2026-04-15 design). Together with 3.a, it provides reference
implementations of both single-model and dual-model variants from
spec §10 — the bias-isolation enablement for the dual-model
adversarial-verification patent claim.

## Install

```bash
# 1. KBTRANSFER + kb-mcp registered (same as 3.a):
pip install -e /path/to/KBTRANSFER
claude mcp add kb-mcp kb-mcp

# 2. Install both skills (3.a is a building block for 3.b):
cp -r examples/skills/kb-distill ~/.claude/skills/
cp -r examples/skills/kb-distill-adversarial ~/.claude/skills/

# 3. Set the verifier model. Default is claude-haiku-4-5 (intra-Claude
#    smoke-test); for real enterprise use, point at a different family:
export VERIFIER_MODEL="openai:gpt-4o"
```

## Use

Inside Claude Code, with a draft pack at `drafts/<pack_id>/` and
tier `enterprise`:

```
/kb-distill-adversarial <pack_id>
```

The skill will:

1. Pre-flight the family check using
   `reference/kb_distiller/family.py`. If the redactor and verifier
   share a family AND policy demands difference, abort early with a
   clear error directing you to set `VERIFIER_MODEL`.
2. Run the full 3.a loop (regex clearing + Pass-2 residual review).
3. Run up to 3 verifier iterations, looping any successful canary
   recoveries back into Pass-2.
4. Stamp `drafts/<pack_id>/.distill-report.json` with both
   `llm_assisted_by` (mode: `dual-model`) and
   `adversarial_verification` blocks.
5. Hand back; **does not** auto-publish.

## What enforces what

The skill is best-effort — even if you trust the agent, an
attestation that claims "verifier was OpenAI" but actually used
another Claude model would be a serious integrity issue. The repo's
defenses are layered:

| Layer | Check | Defense |
|---|---|---|
| Skill | Pre-flight family check | Saves tokens; does not enforce |
| `publish.py` | `_enforce_verifier_family_policy` | Refuses to seal the redaction attestation if `policy.publisher.adversarial_verifier_model_family_must_differ` is `true` AND the block names two same-family models |
| `kb_distiller.family.assert_different_families` | Deterministic classification | Single source of truth; new families added by editing one list |

A skill that stamps a fraudulent block fails at publish, not at
runtime. The server is the trust root, not the agent.

## Provenance recorded in the attestation

After publish, the redaction attestation carries both blocks:

```json
{
  "redaction_level": "strict",
  "policy_applied": "kbtransfer-dual-model",
  "categories_redacted": [...],
  "residual_risk_notes": [...],
  "llm_assisted_by": {
    "model": "claude-opus-4-6",
    "mode": "dual-model",
    "skill": "kb-distill-adversarial@0.1",
    "regex_loop_iterations": 1,
    "residual_review_pass2": true,
    "started_at": "2026-04-15T14:00:00Z",
    "completed_at": "2026-04-15T14:03:22Z",
    "pages_rewritten": 5
  },
  "adversarial_verification": {
    "redactor_model": "claude-opus-4-6",
    "verifier_model": "openai:gpt-4o",
    "redactor_family": "anthropic",
    "verifier_family": "openai",
    "verifier_iterations": 2,
    "probes_per_iteration": 25,
    "recoveries_initial": 4,
    "recoveries_final": 0,
    "recovery_threshold": 0.5,
    "started_at": "2026-04-15T14:01:30Z",
    "completed_at": "2026-04-15T14:03:18Z",
    "policy_family_must_differ": true
  },
  "signature": { "..." }
}
```

A consumer can now make an informed trust decision: not just "this
pack was redacted to strict level" but "redacted by Opus,
adversarially verified by a different-family GPT-4o, and the
verifier failed to recover any canary." That is the full
enablement of the dual-model claim.

## Honest limits

- **Verifier non-determinism.** Two runs of the verifier on the same
  page can return different recovery confidences. The skill mitigates
  by running multiple probes per page and using the conservative
  threshold (0.5 default). Two consecutive runs differing by enough
  to flip pass/fail is itself a signal — see 3.b's dogfood report.
- **Probe choice is hand-crafted.** The five default probe types
  cover the soft checklist categories but a sufficiently creative
  attacker could craft a page where the canary is something the
  default probes miss. Future RFC may formalize a probe taxonomy.
- **Token cost.** A 5-page pack with 5 probes × 3 iterations = 75
  verifier calls. That is the cost of the bias-isolation guarantee;
  publishers may want to short-list pages to verify rather than
  running every page.
- **Trust transfer is consumer-side.** The verifier's "I failed to
  recover" claim is recorded but not independently verifiable by the
  consumer — they trust the publisher's attestation. RFC-0004
  timestamping (Phase 5) makes the claim point-in-time-anchored;
  RFC-0006 revocation lets it be retracted if later proven false.

## See also

- [`../kb-distill/`](../kb-distill/) — the 3.a single-model skill
  this skill builds on.
- `reference/kb_distiller/family.py` — model-family classification,
  the single source of truth.
- `reference/kb_mcp_server/tools/publish.py:_enforce_verifier_family_policy`
  — server-side enforcement.
- `reports/skill-3b-distiller-dual-model.md` — dogfood report for
  this skill.
