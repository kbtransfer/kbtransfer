---
name: kb-distill
description: |
  Drive a single-model (team-tier) distillation pass on a KBTRANSFER draft
  pack. Reads the agent's draft at drafts/<pack_id>/, scrubs structured
  PII via kb/distill/0.1, paraphrases the surrounding context so the
  scrubber finds nothing on the next pass, then performs a residual
  review for soft signals (client names, codenames, monetary amounts,
  stylometric leaks). Stamps the .distill-report.json with an
  llm_assisted_by block so kb/publish/0.1 records LLM provenance in
  the redaction attestation. Use when the user has a draft ready and
  wants single-model team-tier redaction without writing the loop by
  hand.
---

# kb-distill skill — single-model team-tier distillation loop

## What this skill does

KBTRANSFER's `kb/distill/0.1` MCP tool runs a deterministic regex
scrubber + emits a checklist. The checklist by itself is just text —
something has to actually paraphrase the PII-bearing context, redact
soft signals (client names, codenames), and certify the result. That
"something" is normally an LLM driven by the agent. This skill is that
LLM driver, packaged so any KBTRANSFER user can invoke
`/kb-distill <pack_id>` and get a single-model team-tier pass with
zero hand-coding.

The skill encodes the **A+D hybrid loop** locked in the v2 design
discussion (2026-04-15):

- **A (strict loop):** iterate kb/distill → kb/read → paraphrase →
  kb/write until the regex scrubber returns zero findings. Hard cap
  at 3 iterations to prevent infinite loops on adversarial input.
- **D (residual review pass-2):** after the regex loop converges,
  walk every page once more looking for soft signals the regex cannot
  catch — client names, vendor codenames, exact monetary amounts,
  obvious stylometric fingerprints. Edit in place with kb/write.

The skill stays out of `kb/publish/0.1`'s way. Publishing is a
deliberate human-or-agent decision; this skill prepares the draft and
hands back, never auto-publishes.

## Preconditions

1. **kb-mcp server is connected** to your Claude Code session. If
   not, register it with `claude mcp add kb-mcp /path/to/kb-mcp` (the
   `kb-mcp` script is installed by `pip install -e
   /path/to/KBTRANSFER`).
2. **A draft pack exists at `drafts/<pack_id>/`** with at least one
   markdown page under `pages/`. Create one with
   `kb/draft_pack/0.1` if needed.
3. **Tier is `team` or invoked with `mode_override: "single-model"`**.
   This skill only handles single-model semantics. For
   `manual` (individual) the deterministic scrubber alone is enough —
   no skill needed. For `dual-model` (enterprise) you want the
   `kb-distill-adversarial` skill (Phase 3.b, not yet shipped).

## The loop (executed by the agent)

When invoked as `/kb-distill <pack_id>`:

### Step 1 — Establish baseline

Call `kb/distill/0.1` with `pack_id` and (if needed)
`mode_override: "single-model"`.

The response includes `finding_count`, `categories_redacted`, `checklist`,
and `next_steps`. The persisted `.distill-report.json` includes the per-
finding `line_start`, `line_end`, `char_start`, `char_end` fields you
will use to paraphrase precisely.

If `finding_count` is already 0 and `mode` is `single-model`, skip to
**Step 3** — the regex pass added nothing to redact, but pass-2 still
matters because the soft checklist always applies in single-model mode.

### Step 2 — Strict regex-clearing loop (max 3 iterations)

Track `iteration = 1`. Loop:

1. Read `drafts/<pack_id>/.distill-report.json`. For each finding,
   group findings by `page` and load the page text via
   `kb/read/0.1`.
2. For each grouped page, build a single rewrite prompt that:
   - Quotes the page text with line numbers.
   - Lists each finding's (line, char_start, char_end, category,
     placeholder) span — the scrubber has already replaced the literal
     PII with `<PREFIX_NN>` placeholders, so the rewrite goal is to
     **eliminate the placeholders by rewriting the surrounding context
     so the placeholder is no longer needed.** For example, "Email
     <EMAIL_01> for support" should become "Email the support address"
     — not "Email PERSON for support". Generic language beats a renamed
     placeholder every time.
   - Preserves all technical content and code blocks verbatim.
   - Preserves cross-page consistency: if two pages talked about the
     same person, they should still refer to that person the same way
     after rewrite (e.g., both pages now say "the on-call engineer"
     consistently, not "the on-call engineer" on page A and "the
     responder" on page B).
3. Apply the rewritten page via `kb/write/0.1`.
4. Re-call `kb/distill/0.1` with the same `pack_id`. If
   `finding_count == 0`, exit the loop and move to **Step 3**. Else
   increment `iteration`. If `iteration > 3`, **abort** with a clear
   error: the input is producing PII the regex catches that the LLM
   cannot eliminate by rewrite (this happens with structured tables of
   PII, contact lists, etc. — those pages should be removed from the
   draft, not paraphrased).

### Step 3 — Residual review pass (Pass-2 D)

Single pass over every page. The single-model checklist (from
`run_pipeline` in `reference/kb_distiller/pipeline.py`) calls out four
soft categories:

- Client / customer organization names
- Vendor names and internal system codenames
- Exact monetary amounts (generalize to order-of-magnitude ranges)
- Employee identifiers at organization-identifying specificity

For each page:

1. `kb/read/0.1` to load.
2. Scan for the four soft categories and any obvious stylometric
   fingerprints (unusual phrasings, project nicknames, internal
   acronyms, dates narrower than month).
3. If hits found, build a rewrite that generalizes the offending
   spans without losing technical detail.
4. `kb/write/0.1` the rewritten page.

Cross-page consistency rule applies here too: if "Acme" appears on
three pages and you generalize to "the customer", do it on all three.

### Step 4 — Stamp the report and hand off

After Step 3:

1. Read `drafts/<pack_id>/.distill-report.json`.
2. Add (or replace) the `llm_assisted_by` field:

```json
{
  "model": "<the model id you ran on, e.g. claude-opus-4-6>",
  "mode": "single-model",
  "skill": "kb-distill@0.1",
  "regex_loop_iterations": <iterations actually run, 0–3>,
  "residual_review_pass2": true,
  "started_at": "<ISO 8601 Z>",
  "completed_at": "<ISO 8601 Z>",
  "pages_rewritten": <count of distinct pages you wrote at least once>
}
```

   Save the file. `kb/publish/0.1` will read this when it builds the
   redaction attestation — your block becomes the
   `redaction.llm_assisted_by` field that downstream consumers see.
3. **Do NOT call kb/publish/0.1.** Report back to the user with:
   - Final `finding_count` (should be 0).
   - Number of pages rewritten across both passes.
   - The `llm_assisted_by` block you wrote.
   - A short list of the soft signals you found and how you generalized
     them (≤10 items, summarized — give the user enough to spot-check).

## Hard rules

- **Never paraphrase code blocks.** Markdown fenced code (` ``` `) is
  off-limits to LLM rewrite. If a finding is inside a code block, mark
  it for human review and continue. Do not silently strip it.
- **Never invent technical content.** Generalizing "we use Postgres
  14.2 on AWS RDS" to "we use a managed Postgres" is fine.
  Generalizing it to "we use a database" is lossy and wrong — a
  consumer reading the redacted pack should still be able to apply
  the pattern to their own Postgres deployment.
- **Never edit attestation files** (`drafts/<pack_id>/attestations/`)
  directly. Only `.distill-report.json` is yours to mutate; the
  attestations are sealed at publish time.
- **Never call `kb/distill/0.1` more than 4 times total** (1 baseline +
  3 loop iterations max). The hard cap exists to surface bad input,
  not to be worked around.
- **Always preserve the wiki schema's required folders.** If a page is
  in `drafts/<pack_id>/pages/` you may rewrite its body but never
  delete the file; the publisher chose what to include in the draft.
- **Stop on any error from a kb/* tool call.** Surface the error to
  the user; do not retry blindly. The MCP server's error envelopes
  are structured (e.g. `draft_missing`, `no_pages`); read the message
  before deciding what to do.

## What gets handed back to the user

A short report: final finding count, pages touched, summary of
generalizations applied, the `llm_assisted_by` block, and the
recommended next command (`kb/publish/0.1` with the same `pack_id`).
The user decides whether to publish.
