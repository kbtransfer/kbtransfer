# Distiller Skill 3.a — Single-Model Dogfood Report

**Scope:** A Claude Code skill driving the team-tier (`single-model`)
distillation pipeline through a real LLM pass + the two MCP-server
enablers it depends on.
**Target:** publishers running KBTRANSFER under team tier who want
checklist-driven paraphrase + soft-signal redaction without writing
the LLM loop by hand.
**Status:** 100 / 100 tests passing (90 v1 baseline + 10 new
deterministic invariants); 2 adversarial canary tests skipped pending
live-LLM harness.

This is the "C-aşamalı, ilk yarısı" deliverable from the v2 distiller
plan locked on 2026-04-15. The dual-model adversarial sibling (3.b)
is not in this report.

---

## 1. What shipped

```
examples/skills/kb-distill/
├── SKILL.md            full skill instructions (preconditions,
│                       loop A+D hybrid, hard rules, hand-off shape)
└── README.md           install + invocation + provenance fields

reference/kb_distiller/scrubber.py
    ScrubFinding gains line_start / line_end / char_start / char_end.
    scrub_pages() rewritten to compute spans against post-substitution
    text, with cross-pattern overlap resolution by "first pattern wins".

reference/kb_pack/attestation.py
    build_redaction() gains optional llm_assisted_by: dict | None.
    Field is omitted when None (absence is meaningful: pre-skill /
    manual-mode drafts produce attestations without the block).
    C1 invariant on residual_risk_notes preserved.

reference/kb_mcp_server/tools/publish.py
    Threads .distill-report.json's llm_assisted_by through to the
    written redaction.json so downstream consumers see "this pack was
    LLM-paraphrased, by which model, in how many iterations".

tests/test_distiller_skill.py           +10 tests, all deterministic
tests/adversarial/test_distiller_skill_canary.py   +2 tests, skip
                                                    without
                                                    KBTRANSFER_LLM_TESTS=1
```

No spec text changes. The `llm_assisted_by` block is an additive field
in the redaction attestation envelope; v0.1.1 consumers ignore unknown
fields per forward-compat rules. Documenting it in
`autoevolve-spec-v0.1.1.md` is queued for the v0.2 spec
re-publication tracked in `ROADMAP-v2.md`.

---

## 2. Locked design choices the implementation honors

Per the 2026-04-15 design Q&A:

| Karar       | Choice                                       | Where it shows up |
|-------------|----------------------------------------------|-------------------|
| 1 — Tier    | C — aşamalı; 3.a single-model first          | SKILL.md preconditions §3 limit to team / single-model |
| 2 — Konum   | A — `examples/skills/kb-distill/`             | The directory itself, repo-tracked |
| 3 — Loop    | A+D hybrid: strict regex loop + pass-2 review | SKILL.md §"The loop" Steps 2 + 3 |
| 4 — Verifier | C — configurable; deferred to 3.b            | SKILL.md "What this skill is NOT" §"Not for enterprise" |
| 5 — Tests   | C+D — invariants + dogfood report             | This report + tests/test_distiller_skill.py |
| 6 — Server  | B+D — location fields + llm_assisted_by      | scrubber.py + attestation.py + publish.py |

---

## 3. What was proven (deterministic CI)

The 10 new tests in `tests/test_distiller_skill.py` cover the
server-side enablers end to end:

- **Locations are correct.** Four tests assert that for every
  finding, slicing the output page text by `[char_start:char_end]` on
  line `line_start` returns exactly the placeholder string. Verified
  for: single finding per page, multiple findings per page (mix of
  email + phone), findings whose substitution shifts later spans
  leftward (long CC + later IP), and cross-page placeholder
  consistency where each page's spans index into its own output.
- **`llm_assisted_by` flows through.** Four tests on
  `build_redaction`: omitted when not passed, included when passed,
  C1 residual-risk invariant still raises with empty
  `residual_risk_notes`, and the input dict is copied (mutating after
  build does not poison the attestation).
- **publish.py threads the field.** Two tests synthesize a draft
  with a `.distill-report.json` and call
  `_populate_attestations` directly, then read the resulting
  `attestations/redaction.json` from disk and assert the
  `llm_assisted_by` block round-trips byte-for-byte. The negative
  test confirms that a manual-mode report (no `llm_assisted_by`) does
  NOT cause `publish.py` to emit a stub block — absence is preserved.

The full `pytest` run goes from the v1 baseline of 90/90 to **100/100
passing** (+10), with 2 skipped canaries.

---

## 4. What was NOT proven (live LLM)

`tests/adversarial/test_distiller_skill_canary.py` documents the
canary recovery contract: drive the skill against a synthetic
fixture loaded with non-regex-detectable PII (named individuals,
codenames, monetary amounts, narrow time windows), then probe the
rewritten output with a verifier LLM. Pass = the verifier can NOT
recover any canary above the policy's confidence threshold AND the
technical pattern (in the fixture: "circuit-breaker + ingest-rate
cap") IS still recoverable.

Both tests skip with a clear reason when `KBTRANSFER_LLM_TESTS=1` is
not set. Wiring an actual LLM client + harness
(`examples/skills/kb-distill/harness.py`) is deferred to the first
3.a deployment dogfood — at that point a real publisher running the
skill against a real draft will produce concrete artifacts to anchor
the canary test against, rather than this report writing the harness
in a vacuum.

This is the "C+D" half of the test strategy. CI invariants are green
today; live canary lights up when a deployer plugs in their LLM.

---

## 5. Iteration notes — what changed during build

### 5.1 Scrubber rewritten end to end

The original `scrub_pages` used `re.sub` with a closure-side-effect
to collect findings. Adding span locations against the *output* text
required restructuring: now we collect every match across all
patterns first (in pre-substitution coordinates), resolve cross-
pattern overlaps with "first pattern wins" (the canonical PII
priority is EMAIL > SSN > CC > PHONE > IP — a 9-digit SSN must not
get reclassified as a phone fragment by a later pattern), then
substitute left-to-right while tracking the cumulative offset.

The `re.sub`-with-closure pattern was concise but couldn't cleanly
emit post-substitution offsets. The rewrite is ~60 lines vs the
original ~25, but every existing test still passes byte-identical
output. Cross-pattern overlap was an unstated invariant in v1; making
it explicit ("first pattern wins") is now documented in the
implementation comment.

### 5.2 Attestation field is opt-in, absence is signal

Initial sketch had `llm_assisted_by` always present, with a
`{"used": false}` body when the manual mode skipped LLM passes. That
got rejected during the build: a redaction attestation that
*always* announces "no LLM was used" makes downstream consumers
ignore the field as noise. Absence-as-signal — the field appears
only when an LLM actually paraphrased — preserves consumer
attention.

The `test_publish_omits_llm_assisted_by_when_report_lacks_it` test
locks this in. Backsliding (always emitting the block) would fail
that test.

### 5.3 Skill says "do not auto-publish" twice

Both SKILL.md and README.md call out that the skill stops at
attestation prep and hands back to the user. This is deliberate
redundancy: a user who skims one but not the other should still see
the boundary. `kb/publish/0.1` is a deliberate human decision under
v1 semantics (the publisher signs with their own key); a skill that
silently triggered publish would break that.

---

## 6. What 3.b will add on top

3.b is the dual-model enterprise variant. From the design Q&A:

- **Karar 4/C:** verifier model is configurable. Default
  `claude-haiku-4-5` (intra-Claude-family pragmatic split);
  `VERIFIER_MODEL=openai:gpt-4o` style override for true
  inter-provider isolation, which is the patent claim's "bias
  isolation" enablement.
- New skill: `examples/skills/kb-distill-adversarial/SKILL.md`. Wraps
  3.a's loop with a verifier sub-call after Pass-2: the verifier
  reads a redacted page and is asked to recover specific canary
  spans. If it succeeds above the policy's threshold, control loops
  back into Pass-2 with a higher-stringency prompt. If it fails on
  three consecutive iterations (verifier confirms it cannot
  recover), the redaction attestation gains an
  `adversarial_verification` block alongside `llm_assisted_by`.
- Spec §10 currently only requires `adversarial_verifier_model_family_must_differ`
  as policy. 3.b will operationalize the check (refuse to run if the
  verifier model id is in the same family as the redactor) so the
  policy actually has teeth.
- New canary tests in `tests/adversarial/test_distiller_skill_canary.py`
  light up alongside an `adversarial_canary_recovery_under_threshold`
  test that asserts the verifier's recovery confidence stays below
  policy threshold across the fixture set.

---

## 7. Honest limits of 3.a

| Limit | Why it's OK for 3.a |
|---|---|
| Single-model paraphrase can be fooled by stylometric fingerprints | Documented in `residual_risk_notes` (always emitted); 3.b adds the adversarial pass that catches more. |
| The skill cannot itself enforce the "do not paraphrase code blocks" rule — relies on the LLM following SKILL.md | Hard-rule violations would surface in 3.b's verifier (which would recover code-block spans), and in the dogfood report shape; for now it's a human-review checkpoint at hand-off. |
| `harness.py` for live canary is unwritten | Intentional: live harness without a real first deployment is theatre. Deferred to first publisher running 3.a end-to-end. |
| `llm_assisted_by` field not yet in spec text | Tracked in ROADMAP-v2.md; v0.2 spec re-publication will absorb. v0.1.1 consumers ignore the field per forward-compat. |
| Skill assumes `claude-opus-4-6` or similar capable model — small models may fail at consistent cross-page generalization | Acknowledged in SKILL.md §"Not a substitute for human review"; small-model degradation is observable as residual canaries in 3.b once it ships. |

These match the candor of the v1 reports — every limit named, none
hidden.

---

## 8. ROADMAP status update

The 3.a-3.b skill track is parallel to the v2 RFC track in
`ROADMAP-v2.md`. After today's commit:

| Track | Status |
|-------|--------|
| v2 RFCs (Phase 4-6 planning)              | 6 RFCs written + roadmap (commit `085039f`) |
| Distiller skill 3.a single-model           | ✓ done — this report |
| Distiller skill 3.b dual-model adversarial | not started |

3.b can begin immediately; it does not depend on any v2 RFC. It does
benefit from RFC-0004 (timestamping) once that lands, because the
verifier's "I tried at time T to recover and failed" claim is more
durable when timestamped — but that's a reinforcement, not a
prerequisite.

---

## 9. Deliverables in this iteration

```
phase-3a/
├── examples/skills/kb-distill/
│   ├── SKILL.md
│   └── README.md
├── reference/kb_distiller/scrubber.py             # rewrite + locations
├── reference/kb_pack/attestation.py               # +llm_assisted_by
├── reference/kb_mcp_server/tools/publish.py       # threads the field
├── tests/test_distiller_skill.py                  # +10 invariants
├── tests/adversarial/test_distiller_skill_canary.py # +2 skipped canaries
└── reports/skill-3a-distiller-single-model.md     # this file
```

---

*End of distiller skill 3.a dogfood report.*
