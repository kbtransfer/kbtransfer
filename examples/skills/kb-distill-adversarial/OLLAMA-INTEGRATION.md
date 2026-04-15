# Local Ollama verifier for `kb-distill-adversarial`

This companion doc shows how to wire an [Ollama](https://ollama.com)-
served local model as the adversarial verifier. The main
[`SKILL.md`](./SKILL.md) stays model-agnostic and tells the skill
"run the verifier model from `VERIFIER_MODEL`"; this doc gives the
agent the concrete bash recipe to *actually run it* when the chosen
model is served by a local Ollama daemon.

## When to use local Ollama

- **Air-gapped / data-sensitive.** Your draft pack contains content
  you do not want leaving the machine. Hosted verifier APIs are not
  an option.
- **Zero-cost iteration.** Canary recovery runs dozens of probes per
  distill pass. Local inference burns electricity, not API credits.
- **Bias isolation via family diversity.** Ollama serves many
  non-Claude families (llama-, mistral-, qwen-, deepseek-, gemma-).
  Anything that satisfies `assert_different_families(redactor,
  verifier)` against `claude-*` redactor works.

## Prerequisites

- Ollama ≥ 0.5 running at `http://localhost:11434` (default).
- The chosen model pulled locally, e.g. `ollama pull qwen2.5-coder:7b`.
- Claude Code session with the Bash tool available (used to call
  curl; no extra MCP server required).

## One-time sanity check

```bash
# Confirm Ollama is up and the model responds:
curl -s http://localhost:11434/api/tags \
  | python3 -c 'import json,sys; [print(m["name"]) for m in json.load(sys.stdin)["models"]]'

curl -s -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"<your-model>","prompt":"Say exactly: PONG","stream":false}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"])'
```

If either fails: start the daemon (`ollama serve` or restart the
macOS app), pull the model, then retry. The skill has no fallback —
a dead verifier is a fatal error, not a warning.

## Model-family classification for common Ollama tags

`reference/kb_distiller/family.py` already catalogues these prefixes.
Redactor is `claude-*` (anthropic). For family-difference policy to
pass, pick a verifier from one of these:

| Ollama tag example | family (from `family.py`) |
|---|---|
| `llama3.1:8b`, `llama3.3:70b` | `meta` ✓ |
| `mistral:7b`, `mistral-large:latest`, `mixtral:8x22b` | `mistral` ✓ |
| `qwen2.5:7b`, `qwen2.5-coder:7b`, `qwen2.5:72b` | `alibaba` ✓ |
| `deepseek-r1:14b`, `deepseek-coder:6.7b` | `deepseek` ✓ |
| `command-r:35b` | `cohere` ✓ |

**Not yet classified** (would raise `cannot classify` at publish):
`gemma2:*`, `phi3:*`, `yi:*`. To use any of these, add the prefix
to `reference/kb_distiller/family.py:_FAMILY_PREFIXES` first and
ship a test locking the classification in.

## Export the verifier choice

```bash
export VERIFIER_MODEL="qwen2.5-coder:7b"
# Or per-skill-invocation:
VERIFIER_MODEL="llama3.3:70b" /kb-distill-adversarial my.pack.id
```

The skill reads `VERIFIER_MODEL` from the environment. Default
(when unset) is `claude-haiku-4-5` — an intra-Claude-family default
that will REJECT under enterprise-tier policy
(`adversarial_verifier_model_family_must_differ: true`). Setting the
env var is mandatory for enterprise runs.

## The probe curl

The skill's Step 2 verifier loop issues multiple probes per
rewritten page. For each probe, the agent (via the Bash tool) runs:

```bash
PROBE_PROMPT=$(cat <<'EOF'
You are reading ONE redacted page from a knowledge pack. Answer only
based on what this page literally says. Do NOT infer from external
knowledge. If the page does not contain the answer, reply exactly:
"cannot tell" followed by confidence 0.0.

Page:
---
<PASTE THE REDACTED PAGE TEXT HERE>
---

Question: <PROBE_TYPE — e.g. "What is the customer organization's name?">

Reply in exactly this format:
<ANSWER>
confidence: <0.0–1.0>
EOF
)

curl -s -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "
import json, os, sys
print(json.dumps({
    'model': os.environ['VERIFIER_MODEL'],
    'prompt': '''$PROBE_PROMPT''',
    'stream': False,
    'options': {'temperature': 0.1, 'num_predict': 80}
}))
")" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"])'
```

Key choices:

- **`temperature: 0.1`** — low, not zero. Zero makes the verifier
  deterministic but also brittle; 0.1 samples enough variation to
  catch canary leaks the greedy answer would miss.
- **`num_predict: 80`** — the expected reply is a short noun phrase
  + confidence line. 80 tokens is plenty; avoids verifier rambling.
- **`stream: false`** — one JSON response, easier to parse.
- **Page text inlined into the prompt.** The verifier MUST see only
  the single redacted page — no skill context, no redactor reasoning,
  no other pages. Bias isolation depends on this.

## Batched Python alternative (equivalent, often faster)

Per-probe Bash curl is the reference pattern above because it is
transparent and needs no extra tooling, but a batched Python helper
that loops over probes in one process is an allowed alternative.
Equivalence requires only that bias isolation is preserved: each
probe is still a **fresh HTTP request** with a single-page prompt
and no shared conversation state. A helper like:

```python
# /tmp/probe_runner.py — conceptual sketch, not a committed artifact
import json, os, urllib.request
for probe in probes:  # probes = [(page_id, category, page_text, question), ...]
    body = json.dumps({
        "model": os.environ["VERIFIER_MODEL"],
        "prompt": build_prompt(probe.page_text, probe.question),
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 80},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        print(probe.page_id, probe.category,
              json.loads(r.read())["response"])
```

…is acceptable, and the 2026-04-15 full-cycle dogfood found it
faster in practice (fewer Bash tool permission prompts, no per-call
shell startup). The skill does not prescribe either form; choose
what the invoking agent finds clearer. Requirements that remain
non-negotiable:

- Fresh HTTP request per probe (no Ollama session reuse, no
  cross-probe prompt concatenation).
- Verifier sees only the page text and the probe question.
- Results are collected and classified by the same recovery
  threshold in either path.

## Probe categories

The skill composes 3-5 probes per page from these categories (see
[`SKILL.md §Step 2`](./SKILL.md#step-2--adversarial-verifier-loop-new-max-3-iterations)):

| Category | Example probe |
|---|---|
| client | "What is the customer / client organization's name?" |
| codename | "What is the internal project codename mentioned?" |
| monetary | "What dollar amount is mentioned in this page?" |
| employee | "What person's name is mentioned?" |
| time | "What specific date or time window is named?" |

A "recovery" is any answer that returns a concrete value with
confidence ≥ `policy.publisher.adversarial_recovery_threshold`
(default 0.5). "cannot tell" at any confidence is NOT a recovery.

## Collecting and acting on recoveries

After running all probes across all pages for iteration `v`:

- If zero recoveries → exit verifier loop, stamp
  `adversarial_verification` block, hand off.
- If ≥1 recoveries → for each recovered span, run a one-shot Pass-2
  rewrite prompt naming the recovered text explicitly. Re-run the
  verifier loop at `v+1`. Cap at 3 iterations; fail past that.

## Performance notes (qwen2.5-coder:7b specifically)

The 7B coder model is a reasonable first dogfood choice — fast,
fits on consumer hardware, classified as `alibaba` (satisfies
family-difference). Caveats:

- **Coder-tuned ≠ strongest for natural language recall.** A 7B
  general chat model (e.g. `mistral:7b`) may recover more canaries
  per probe. If your 3.b dogfood shows low recoveries across the
  board, try a non-coder model of the same size before assuming
  your redaction is solid.
- **Context window.** qwen2.5-coder:7b ships with a 32K context by
  default — plenty for a single page + probe. No chunking needed.
- **Latency.** Expect ~1-2s per probe on a 2023+ Mac Silicon with
  the 7B model loaded. A 5-page pack × 5 probes × 3 iterations is
  ~75 probes → ~2-3 minutes wall-clock.

For production enterprise runs, step up to at least 14B (e.g.
`qwen2.5:14b`) or ideally 70B-class (`llama3.3:70b`). The patent
claim's bias-isolation strength scales with verifier capability; a
7B verifier that fails to recover is weaker evidence than a 70B
verifier failing to recover.

## Permissions hint for Claude Code

Each `Bash` tool call to curl may prompt for permission. To run a
distill pass without constant prompting, add this rule before
invoking the skill:

Settings → Permissions → Allow:
```
Bash(curl -s http://localhost:11434/**)
Bash(curl -s -X POST http://localhost:11434/**)
```

The skill's Bash calls are exclusively to `localhost:11434`;
allowing that glob scopes the approval narrowly.
