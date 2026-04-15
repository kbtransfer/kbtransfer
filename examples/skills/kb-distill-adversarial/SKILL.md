---
name: kb-distill-adversarial
description: |
  Drive a dual-model (enterprise-tier) distillation pass on a
  KBTRANSFER draft pack. Wraps the single-model kb-distill loop with
  an adversarial verifier sub-call: after redaction, a verifier model
  from a different family probes each rewritten page for canary
  recovery — naming the customer, recovering codenames, identifying
  the employee — and any successful recovery loops control back into
  Pass-2 with a stricter prompt. Stamps the .distill-report.json with
  both an llm_assisted_by block (mode: dual-model) AND an
  adversarial_verification block recording redactor + verifier model
  identities, family names, iteration count, and recovery outcomes.
  publish.py refuses to seal the pack if the verifier and redactor
  share a model family AND policy demands difference. Use when the
  user has a draft ready, tier is enterprise, and the publisher
  policy has adversarial_verifier_model_family_must_differ: true.
---

# kb-distill-adversarial skill — dual-model adversarial loop

## What this skill does

KBTRANSFER's spec §10 names "dual-model adversarial verification" as
the strictest distillation mode and the patent claim's
bias-isolation enablement. The reference pipeline emits the checklist
("a model from a different family than the redactor MUST fail to
recover any redacted span above the policy's confidence threshold")
but cannot drive the verifier itself — the MCP server does no LLM
inference. This skill is that verifier driver.

The skill builds on the **3.a single-model kb-distill skill** and
adds the verifier loop on top:

1. **3.a's strict regex loop** — kb/distill → kb/read → paraphrase →
   kb/write until findings = 0 (max 3 iterations).
2. **3.a's Pass-2 residual review** — soft signals (client names,
   codenames, monetary amounts).
3. **NEW: adversarial verifier loop** — a verifier model from a
   different family is fed each rewritten page and asked to recover
   specific canary identities. If recovery confidence exceeds the
   policy threshold, control returns to Pass-2 with a stricter
   prompt naming the recovered span. Maximum 3 verifier iterations;
   if recovery still happens after 3, abort with a structured
   "adversarial_recovery_persistent" error (some content is
   intrinsically un-redactable without losing technical value — those
   pages should be dropped from the draft).
4. **Stamp + hand off** — `llm_assisted_by` (mode: `dual-model`)
   AND `adversarial_verification` blocks written to
   `.distill-report.json`. publish.py reads them; if model families
   match AND policy demands difference, publish.py refuses. Skill
   cannot lie its way past this — the family check lives in the
   server.

## Preconditions

1. **kb-mcp server connected.**
2. **Draft pack at `drafts/<pack_id>/`** with markdown pages.
3. **Tier is `enterprise`** (or invocation with
   `mode_override: "dual-model"`). For team-tier `single-model`,
   use the `kb-distill` skill instead.
4. **`VERIFIER_MODEL` environment variable set.** Default is
   `claude-haiku-4-5` — an intra-Claude-family pragmatic split that
   covers smoke-test scenarios but does NOT satisfy the
   `adversarial_verifier_model_family_must_differ: true` policy that
   the enterprise template ships with. For real enterprise use, set
   `VERIFIER_MODEL` to a different-family model id. For local Ollama
   setup, see the companion
   [`OLLAMA-INTEGRATION.md`](./OLLAMA-INTEGRATION.md) in this
   directory. Recognized prefixes (see
   `reference/kb_distiller/family.py`):
   - `gpt-*`, `o1-*`, `o3-*`, or `openai:*` — OpenAI family
   - `gemini-*`, `palm-*`, or `google:*` — Google family
   - `llama-*` or `meta:*` — Meta family
   - `mistral-*`, `mixtral-*` — Mistral family
   - `command-*` — Cohere
   - `deepseek-*` — DeepSeek
   - `qwen-*` — Alibaba
   - `grok-*` — xAI

   Unknown prefixes are *refused*, not silently accepted — adding a
   new family means a code change in `family.py`.

## The loop (executed by the agent)

When invoked as `/kb-distill-adversarial <pack_id>`:

### Step 0 — Pre-flight family check

1. Read `.kb/policy.yaml` via `kb/policy_get/0.1`.
2. Identify your own model id (the "redactor model" — the one running
   *this* skill body, e.g. `claude-opus-4-6`).
3. Read `VERIFIER_MODEL` env; if unset, default to `claude-haiku-4-5`.
4. If `policy.publisher.adversarial_verifier_model_family_must_differ`
   is `true`:
   - The skill SHOULD pre-flight the family check (deterministic, no
     LLM call): see the family classification table in
     **Preconditions**. If redactor and verifier are the same family,
     **abort immediately** with a clear error directing the user to
     set `VERIFIER_MODEL=<different-family-id>`. Do not proceed and
     waste tokens; publish.py will reject anyway.

### Step 1 — Run the 3.a sub-loop (single-model regex + Pass-2)

Execute exactly the steps from `examples/skills/kb-distill/SKILL.md`
(strict regex loop max 3 iter + Pass-2 residual). Track:

- `regex_loop_iterations` — number of regex-clearing passes (0–3).
- `pass2_pages_rewritten` — distinct pages touched in Pass-2.

### Step 2 — Adversarial verifier loop (NEW; max 3 iterations)

For verifier iteration `v` from 1 to 3:

1. **Pick canary probes per page.** For each rewritten page, compose
   3-5 verifier prompts of the form:
   - "Reading only this page, what is the customer organization's
     name? Reply with the name only, or 'cannot tell' with a
     confidence 0–1."
   - "Reading only this page, what is the internal project codename?
     Same format."
   - "Reading only this page, what dollar amount is mentioned?
     Reply with the number only, or 'cannot tell' with confidence."
   - One probe per soft category: client, codename, amount,
     employee, narrow time window.
2. **Run the verifier model** (the one named by `VERIFIER_MODEL`, or
   the default) against each probe. The verifier MUST be a fresh
   conversation each time — it sees only the page text and the
   probe, no skill instructions, no other context, no chain of
   thought from the redactor. Probe execution may use per-probe
   Bash calls OR a batched helper script (e.g. a small Python
   runner that loops over probes in one process); see
   [`OLLAMA-INTEGRATION.md` §Batched Python alternative](./OLLAMA-INTEGRATION.md#batched-python-alternative-equivalent-often-faster).
   Bias isolation (fresh request, single-page prompt, no shared
   state across probes) is what matters, not the shell path.
3. **Collect recoveries.** A "recovery" is any verifier response
   that returns a concrete answer (not "cannot tell") with
   confidence ≥ `policy.publisher.adversarial_recovery_threshold`
   (default 0.5 if absent).
4. **If zero recoveries across all pages** → exit verifier loop.
   Proceed to Step 3.
5. **If one or more recoveries** → for each recovered span, return
   to a one-shot Pass-2 rewrite with a prompt naming the recovered
   span explicitly: "the verifier recovered '<span>' from this page;
   rewrite the surrounding context to make recovery impossible
   without losing the technical pattern." Apply via `kb/write/0.1`.
6. After all rewrites, increment `v`. If `v > 3`, **abort** with
   `adversarial_recovery_persistent`: include the unfixed
   recoveries in the error so the user can decide whether to drop
   the page from the draft.

### Step 3 — Stamp the report and hand off

After Step 2 exits cleanly:

1. Read `drafts/<pack_id>/.distill-report.json`.
2. Write (or replace) `llm_assisted_by`:

```json
{
  "model": "<redactor model id>",
  "mode": "dual-model",
  "skill": "kb-distill-adversarial@0.1",
  "regex_loop_iterations": <0–3>,
  "residual_review_pass2": true,
  "started_at": "<ISO 8601 Z>",
  "completed_at": "<ISO 8601 Z>",
  "pages_rewritten": <distinct page count>
}
```

3. Write (or replace) `adversarial_verification`:

```json
{
  "redactor_model": "<redactor id, same as llm_assisted_by.model>",
  "verifier_model": "<verifier id from env or default>",
  "redactor_family": "<from family.py classification>",
  "verifier_family": "<from family.py classification>",
  "verifier_iterations": <0–3>,
  "probes_per_iteration": <count of probes you ran per iteration>,
  "recoveries_initial": <count from iteration 1>,
  "recoveries_final": 0,
  "recovery_threshold": <policy threshold actually applied>,
  "started_at": "<ISO 8601 Z>",
  "completed_at": "<ISO 8601 Z>",
  "policy_family_must_differ": <true|false from policy>
}
```

   `recoveries_final` MUST be 0 to reach this step (Step 2 exits
   only on zero recoveries or abort).

4. Save the file.
5. **Do NOT call `kb/publish/0.1`.** Hand back to the user with:
   - Final findings count (0).
   - Verifier iterations used (0–3).
   - Initial vs final recovery counts.
   - Both blocks for the user to spot-check.
   - The recommended next command.

## Hard rules

- **Family check is server-enforced.** publish.py independently runs
  the family check from `kb_distiller.family.assert_different_families`.
  A skill that stamps a fraudulent (matching-family) block will be
  rejected at publish. Do not waste cycles trying.
- **Verifier sees only the page.** No skill instructions, no
  redactor's reasoning, no other pages. Bias isolation is the entire
  point; leaking redactor context defeats it.
- **Same hard rules from 3.a apply** (no code-block paraphrase, no
  invented technical content, never delete pages, stop on any kb/*
  error).
- **`recoveries_final` MUST equal 0 when stamping.** If you cannot
  drive recoveries to 0 within 3 iterations, abort with
  `adversarial_recovery_persistent` and write nothing to
  `.distill-report.json`. Half-done attestations are worse than no
  attestation.
- **Token budget.** A real verifier loop on a 5-page pack with 5
  probes per page over 3 iterations is 75 verifier calls. Cost-conscious
  publishers may want to set `policy.publisher.adversarial_verifier_max_calls`
  and have the skill abort early if the budget would be exceeded;
  this is a forward-compat hook, not yet enforced by the server.

## What gets handed back

A short report: final regex+pass-2 outcome, verifier iteration
count, initial/final recovery counts, both metadata blocks, and the
next command (`kb/publish/0.1`). The user decides whether to publish.
