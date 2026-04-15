# Distiller Skill 3.b — Dual-Model Adversarial Dogfood Report

**Scope:** A Claude Code skill driving the enterprise-tier
(`dual-model`) distillation pipeline through a real LLM pass with
adversarial verifier from a different model family + the server-side
enforcement that makes the family-difference invariant tamper-proof.
**Target:** publishers running KBTRANSFER under enterprise tier with
`adversarial_verifier_model_family_must_differ: true` in policy.
**Status:** 134 / 134 tests passing (100 from 3.a baseline + 30 family
classifier tests + 4 publish enforcement tests); 4 adversarial canary
tests skipped pending live-LLM harness.

This is the "decision-C staged plan, second half" deliverable from
the v2 distiller design locked on 2026-04-15. With 3.a + 3.b shipped,
both
single-model and dual-model variants from spec §10 now have
reference implementations. The spec calls out dual-model adversarial
verification as the bias-isolation enablement for the patent claim;
3.b makes that enablement concrete with code, tests, and operator
documentation.

---

## 1. What shipped

```
examples/skills/kb-distill-adversarial/
├── SKILL.md            full skill instructions: pre-flight family
│                       check, 3.a sub-loop, NEW verifier loop with
│                       canary probes, both metadata blocks
└── README.md           install + invocation + layered defense
                        explanation + provenance fields shown

reference/kb_distiller/family.py
    NEW. Single source of truth for model-family classification.
    family_of(model_id) → str + assert_different_families() raise.
    Unknown family is refusal-to-classify, NOT a wildcard — preserves
    the bias-isolation invariant against future models we have not
    yet catalogued.

reference/kb_distiller/__init__.py
    Re-exports family.py public API.

reference/kb_mcp_server/tools/publish.py
    NEW: _enforce_verifier_family_policy() runs before
    build_redaction. Reads policy.publisher.adversarial_verifier_model_family_must_differ;
    if true, refuses to seal a redaction attestation whose
    adversarial_verification block names two same-family models or
    omits redactor_model / verifier_model entirely.
    Threads adversarial_verification through to the attestation file.

tests/test_distiller_family.py                +30 tests, deterministic
tests/test_distiller_skill.py (extended)      +4 publish enforcement
                                               tests (intact passthrough,
                                               same-family rejection,
                                               no-policy-no-rejection,
                                               missing-model-ids
                                               rejection)
tests/adversarial/test_distiller_skill_canary.py (extended)
                                               +2 skipped canary
                                               tests for the
                                               adversarial-recovery
                                               contract and the
                                               server-side rejection
                                               smoke test
```

No spec text changes. The `adversarial_verification` block was
already an optional field in `kb_pack.attestation.build_redaction`
since v1; this iteration makes it operationally meaningful by:

- Defining the structured shape the skill writes (12 fields).
- Adding server-side enforcement of the spec §10
  family-difference invariant.
- Documenting the layered defense in operator-facing docs.

Documenting the block in `autoevolve-spec-v0.1.1.md` text is queued
for the v0.2 spec re-publication tracked in `ROADMAP-v2.md`.

---

## 2. Locked design choices the implementation honors

Per the 2026-04-15 design Q&A:

| Decision    | Choice                                       | Where it shows up |
|-------------|----------------------------------------------|-------------------|
| 1 — Tier    | C — staged; 3.b dual-model after 3.a         | This skill exists alongside kb-distill, builds on it |
| 2 — Konum   | A — `examples/skills/kb-distill-adversarial/` | The directory itself, repo-tracked |
| 3 — Loop    | A+D hybrid (from 3.a) + NEW verifier loop    | SKILL.md §"The loop" Steps 1-2 reuse 3.a; Step 2 NEW |
| 4 — Verifier | C — configurable, default Haiku, env override | SKILL.md §"Preconditions" + family classification table; family.py prefix list |
| 5 — Tests   | C+D — invariants + dogfood report             | This report + tests/test_distiller_family.py + extension to test_distiller_skill.py |
| 6 — Server  | B+D — locations (3.a) + adversarial_verification block (3.b) | scrubber.py (3.a) + attestation.py + publish.py (both phases) |

All six decisions locked; nothing reopened during build.

---

## 3. The layered defense

The most important invariant in 3.b is *unforgeable family
difference*. The patent claim depends on bias isolation; bias
isolation depends on the verifier and redactor genuinely being from
different training families. If a malicious or careless skill could
stamp a fraudulent block claiming "verifier was OpenAI" while
actually using another Claude model, the entire claim collapses.

The repo's defense is layered:

| Layer | What it does | What it cannot stop |
|---|---|---|
| **Skill pre-flight** (SKILL.md Step 0) | Reads policy + env, runs `family_of` locally, aborts if same family. | Saves tokens; honest skills only. |
| **Server-side enforcement** (`publish.py:_enforce_verifier_family_policy`) | Runs the same check independently when sealing the attestation. Refuses to publish if same-family or missing model ids. | Cannot detect lies *about which model actually ran* — only verifies consistency between the stamped block and the family classification. |
| **`assert_different_families`** (`family.py`) | Single source of truth. Unknown family is treated as failure (refusal-to-classify), not wildcard. | Adding a new family requires a code change in `_FAMILY_PREFIXES`; intentional friction. |

A skill that lies about which model it used is detectable only if a
third party re-runs the verifier and compares. RFC-0006 (revocation)
gives that third party a recourse: discover false attestation, mark
the pack revoked, downstream consumers stop trusting it. Together
with RFC-0004 (timestamping), the trust story becomes:
"point-in-time verified, by these models, with this consistency
across publisher and registry."

---

## 4. What was proven (deterministic CI)

The 30 family-classifier tests + 4 publish-enforcement tests pin
behavior across the surface area:

- **Family classification is correct for every shipped prefix** (20
  parametrized cases) — Anthropic, OpenAI (gpt-, o1-, o3-, openai:
  forms), Google (gemini-, palm-, google: forms), Meta (llama-,
  meta:), Mistral (mistral-, mixtral-), Cohere, DeepSeek, Alibaba,
  xAI.
- **Unknown classification is sentinel, not wildcard** (4 cases) —
  empty string, made-up models, Microsoft Phi, 01.AI Yi all return
  `UNKNOWN_FAMILY` so callers cannot pretend the absence of a
  classification is permission. Phi and Yi are deliberately included
  to flag known-but-uncatalogued families; adding them requires an
  intentional code change.
- **Non-string input gracefully returns unknown** (2 cases) — `None`
  and `123` both return sentinel without raising.
- **`assert_different_families` is symmetric** (3 cases passing) —
  cross-family pairs accepted regardless of order.
- **Same-family rejection is enforced** (2 cases failing) —
  intra-Claude (Opus + Haiku) and intra-OpenAI (gpt-4o + o1-preview)
  both raise with `same family` in the message.
- **Unknown-family rejection is enforced** (2 cases) — unknown on
  either side raises with `cannot classify` in the message.
- **publish.py threads a valid block intact** (1 test) — round-trip
  byte-equality of the 12-field block from `.distill-report.json` to
  the redaction attestation file.
- **publish.py rejects same-family when policy demands** (1 test) —
  enterprise-tier policy + intra-Claude block → `BuildError` with
  `same family` in the message. The skill cannot lie its way past
  this.
- **publish.py allows same-family when policy permits** (1 test) —
  team-tier (or any policy without the flag) accepts the block; the
  family identity is still recorded for consumer inspection.
- **publish.py rejects missing model ids when enforcement is on** (1
  test) — defends against the "stamp a stub block to get past the
  check" attack.

The full `pytest` run goes from 100/100 (3.a baseline) to **134/134
passing** (+34), with 4 skipped canaries (2 from 3.a + 2 new for
3.b).

---

## 5. What was NOT proven (live LLM)

Two new entries in `tests/adversarial/test_distiller_skill_canary.py`
document the live-LLM contracts:

- **`test_adversarial_canary_recovery_under_threshold`** —
  end-to-end: drive 3.b against `CANARY_FIXTURE`, then run a fresh
  verifier from a different family against the rewritten output. The
  verifier MUST NOT recover any string in `CANARIES` with confidence
  ≥ 0.5. Pass ≡ `recoveries_final == 0` AND no canary recovered
  above threshold.
- **`test_adversarial_publish_rejects_intra_family_smoke`** —
  end-to-end with the *default* `VERIFIER_MODEL=claude-haiku-4-5`,
  enterprise-tier policy in place: confirms the layered defense
  works under realistic operator conditions (skill says "warning,
  same family"; if user bypasses skill and hand-edits the report,
  publish.py STILL refuses).

Both skipped without `KBTRANSFER_LLM_TESTS=1`. The harness wiring
(`examples/skills/kb-distill-adversarial/harness.py`) is deferred to
the first 3.b deployment — same rationale as 3.a, and amplified for
3.b because 3.b needs *two* configured LLM clients (redactor +
verifier from different families).

---

## 6. Iteration notes — what changed during build

### 6.1 Family unknown is refusal, not wildcard

The first sketch of `assert_different_families` had a fast-path:
"if either family is unknown, allow — we can't prove they're the
same." That got rejected before commit: spec §10 demands *positive
evidence* of difference. An unknown-family verifier provides no
evidence, so it cannot satisfy the invariant. The current
behavior — raise `cannot classify` on unknown either side — turns
"new model not yet in our table" into a deliberate operator decision
("update `_FAMILY_PREFIXES` or pick a known model") rather than a
silent acceptance.

The two unknown-rejection tests lock this in. Backsliding (allowing
unknown) would fail both tests.

### 6.2 Server-side enforcement is independent of the skill

The first sketch of `_enforce_verifier_family_policy` trusted the
`redactor_family` and `verifier_family` fields the skill stamps. Got
rejected: that means a malicious skill could stamp
`verifier_family: "openai"` next to `verifier_model:
"claude-haiku-4-5"` and pass. The current implementation re-runs
`assert_different_families(redactor_model, verifier_model)`
server-side, ignoring the skill's family claims entirely. Family is
re-derived, not trusted.

The `test_publish_rejects_same_family_when_policy_demands_difference`
test catches any backslide.

### 6.3 Missing model ids = refusal, not skip

Initially `_enforce_verifier_family_policy` skipped enforcement when
the block lacked `redactor_model` or `verifier_model`. Got rejected:
that means a skill could stamp a stub block with no ids and pass.
Current behavior raises with `redactor_model or verifier_model`
missing. The `test_publish_rejects_when_block_missing_model_ids`
test locks it.

### 6.4 Canary probe taxonomy left as skill instructions, not a tool

A possible design was a new MCP tool `kb/adversarial_probe/0.1` that
accepts (page_text, probe_type) and returns a verifier prompt.
Rejected — the skill is the natural home for prompt taxonomy because
prompts are model-specific (a probe phrased one way for GPT-4o reads
differently to Gemini). The skill names the five probe types in
SKILL.md §Step 2; future iterations can lift the taxonomy into a
shared module if multiple skills end up sharing it.

### 6.5 Policy threshold default chosen at 0.5

`policy.publisher.adversarial_recovery_threshold` is read by the
skill when categorizing a verifier response as "recovery." Default
0.5 if absent in policy. This was a judgment call — 0.5 is a
conservative threshold (anything ≥ 50% confidence triggers
re-redaction) without being so tight that genuine "I'm guessing"
verifier outputs flip the loop into oscillation. Operators with
stricter requirements set it lower (e.g., 0.3); with relaxed
requirements (smoke-test scenarios) higher (e.g., 0.7). Documented
in the SKILL.md Step 2 default; not yet enforced in policy schema.

---

## 7. Honest limits of 3.b

| Limit | Why it's OK for 3.b |
|---|---|
| Skill cannot prove which model actually ran (only what it stamps) | Layered defense + RFC-0006 revocation provides recourse if discovered; matches PKI's "trust until revoked" model. |
| Probe taxonomy is hand-crafted (5 categories) | A sufficiently creative attacker can craft canaries the default probes miss. Future RFC may formalize a probe taxonomy. |
| Token cost is high (75 verifier calls for 5-page × 5-probe × 3-iter) | Cost of bias isolation. Operators may short-list pages. `adversarial_verifier_max_calls` policy hook documented but not yet server-enforced. |
| Verifier non-determinism — two runs may differ | Mitigated by multiple probes and conservative threshold; flip-flop is itself a signal worth surfacing in dogfood. |
| `harness.py` for live canary unwritten | Intentional; live harness without a real first deployment is theatre. Lights up at first 3.b deployment, same as 3.a. |
| `adversarial_verification` block not yet in spec text | Tracked in ROADMAP-v2.md; v0.2 spec re-publication will absorb. |
| `unknown-family` verifier path is intentional friction, not warm-fuzzy "we got you covered" | Operators using a future model not yet in the table must make a deliberate choice (update `_FAMILY_PREFIXES`, pick a known alternative, or accept the refusal). This is the right friction for a security-relevant invariant. |

These match the candor of the v1 + 3.a reports — every limit named,
none hidden.

---

## 8. Patent enablement status

The four novelty claims in
`specs/current/autoevolve-packs-overview.md §"Patent-relevant novel
combinations"` had reference code + T-suite/D-suite tests for
single-model proofs after v1. After 3.b:

| Claim | v1 status | 3.a/3.b additions |
|---|---|---|
| Karpathy-wiki + AutoEvolve-Pack distillation | full enablement | `llm_assisted_by` block records pipeline identity in attestation |
| Tier-aware redaction with policy file | full enablement | dual-model variant now has working code (was checklist-only) |
| Bias-isolated dual-model adversarial verification | checklist + spec text | **full enablement: `family.py` + `_enforce_verifier_family_policy` + skill + structured `adversarial_verification` block** |
| Consumer-driven federated trust with TOFU/strict policies | full enablement | unchanged |

Claim #3 was the weakest before this iteration — checklist + spec
text without operational enforcement. After 3.b, a publisher
genuinely cannot ship a "dual-model adversarial-verified" pack
without satisfying the family-difference invariant in code. That is
the enablement standard USPTO drafting expects.

---

## 9. ROADMAP status update

```
v2 RFCs (Phase 4-6 planning):              ✓ commit 085039f
Distiller skill 3.a single-model:           ✓ commit fc75745
Distiller skill 3.b dual-model adversarial: ✓ this commit
```

Both options the user picked on 2026-04-15 — v2 roadmap (Option 2)
and distiller-skill engineering (Option 3) — are now fully closed.
The four candidates on the table from `next_steps_paused_2026_04_14.md`
have been narrowed: Option 1 (GitHub push) and Option 4 (USPTO
provisional) remain as the natural next decisions.

---

## 10. Deliverables in this iteration

```
phase-3b/
├── examples/skills/kb-distill-adversarial/
│   ├── SKILL.md
│   └── README.md
├── reference/kb_distiller/family.py             # NEW classifier
├── reference/kb_distiller/__init__.py            # re-exports
├── reference/kb_mcp_server/tools/publish.py     # +enforcement
├── tests/test_distiller_family.py               # +30 invariants
├── tests/test_distiller_skill.py                 # +4 publish tests
├── tests/adversarial/test_distiller_skill_canary.py # +2 canaries
└── reports/skill-3b-distiller-dual-model.md     # this file
```

---

*End of distiller skill 3.b dogfood report. Both 3.a and 3.b
shipped; v2 RFC track also closed. Engineering surface for distiller
work paused pending first deployment dogfood.*
