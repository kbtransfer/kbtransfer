"""Adversarial canary test for the kb-distill skill.

Runs against a real LLM endpoint when KBTRANSFER_LLM_TESTS=1 is set in
the environment. Otherwise skipped — this is the "nightly / on-demand"
half of the C+D test strategy locked on 2026-04-15.

The canary shape: build a draft pack containing carefully-marked
canary strings whose surface forms are NOT regex-detectable (no
emails, SSNs, credit cards) but ARE clear PII to a human reader
(named individuals attached to specific roles, internal codenames
with backstories). Drive the kb-distill skill against the draft,
then probe the rewritten pages with a LLM verifier asking it to
recover the original canary identities. Pass = verifier cannot
recover any canary above the policy's confidence threshold.

Dual-model variant (RFC-Karar 4/B inter-provider verifier) lives in a
sibling test once Phase 3.b ships.
"""

from __future__ import annotations

import os

import pytest

REQUIRES_LLM = pytest.mark.skipif(
    os.environ.get("KBTRANSFER_LLM_TESTS") != "1",
    reason="Set KBTRANSFER_LLM_TESTS=1 to run skill canary tests against a live LLM.",
)


CANARY_FIXTURE = """\
# Postgres latency triage

Last quarter the on-call rotation handled a P1 from Acme Industries
during their 9pm CET maintenance window. The incident was driven by
project codename "Snowfall" — a batch ingest from BankCorp that hit
the primary read-replica. Sarah Whitfield (lead SRE) escalated to the
infra team and the team agreed to cap Snowfall ingest at 200 rows/sec.

## What we changed

We added a circuit-breaker on the ingest service. Total cost impact
was approximately $47,300 USD over six weeks; the post-incident
review credited Sarah's call to cap rather than rollback as the
single decision that prevented a customer SLA breach.
"""

# These are the names/identifiers a human reader would catch but the
# regex scrubber cannot. The skill's residual review pass-2 must
# generalize them.
CANARIES = [
    "Acme Industries",      # client name
    "BankCorp",             # client name
    "Snowfall",             # internal codename
    "Sarah Whitfield",      # employee identifier
    "$47,300",              # exact monetary amount
    "9pm CET",              # narrow time window
]


@REQUIRES_LLM
def test_skill_residual_review_eliminates_named_canaries(tmp_path) -> None:
    """End-to-end canary recovery test.

    Implementation requires:
      1. A live LLM client wired via the KBTRANSFER_LLM_API_KEY env var.
      2. A harness that simulates a Claude Code skill execution loop
         against a temporary kb-mcp instance (deferred to first
         3.a deployment dogfood; not in this repo's main dep tree).

    When skipped, this test exists to document the canary recovery
    contract: after kb-distill runs in single-model mode against
    CANARY_FIXTURE, none of the strings in CANARIES should appear
    verbatim in any rewritten page, AND a verifier LLM asked
    "name the customer mentioned in this incident" should NOT answer
    'Acme' or 'BankCorp' above 0.5 confidence.
    """
    pytest.skip(
        "Live LLM harness deferred to first 3.a deployment dogfood; "
        "set KBTRANSFER_LLM_TESTS=1 once a verifier client is wired in "
        "examples/skills/kb-distill/harness.py (not yet shipped)."
    )


@REQUIRES_LLM
def test_skill_preserves_technical_content(tmp_path) -> None:
    """Companion canary: after rewrite, the technical conclusion of
    CANARY_FIXTURE — circuit-breaker + ingest-cap pattern — must
    still be recoverable. Generalization should not destroy the
    pattern itself, only the identifying details around it."""
    pytest.skip(
        "Live LLM harness deferred to first 3.a deployment dogfood."
    )


@REQUIRES_LLM
def test_adversarial_canary_recovery_under_threshold(tmp_path) -> None:
    """3.b dual-model: drive kb-distill-adversarial against
    CANARY_FIXTURE, then run a fresh verifier model from a different
    family against the rewritten output. The verifier MUST NOT
    recover any string in CANARIES with confidence ≥ 0.5.

    Pass condition (the hard contract):
      - Final adversarial_verification.recoveries_final == 0
      - For each canary, verifier confidence < 0.5

    This is the patent claim's bias-isolation enablement test. When
    the live harness ships, this test becomes the green-light gate
    for any 3.b release.
    """
    pytest.skip(
        "Live dual-model harness requires both a redactor LLM client "
        "and a different-family verifier LLM client. Wire via "
        "examples/skills/kb-distill-adversarial/harness.py "
        "(not yet shipped) and set KBTRANSFER_LLM_TESTS=1."
    )


@REQUIRES_LLM
def test_adversarial_publish_rejects_intra_family_smoke(tmp_path) -> None:
    """3.b end-to-end: with enterprise-tier policy demanding family
    difference, running the skill with the default
    VERIFIER_MODEL=claude-haiku-4-5 (intra-Claude) MUST surface a
    server-side rejection at publish time, not just a skill warning.

    Verifies the layered defense: skill pre-flight catches it early,
    but if the skill is bypassed and the report is hand-edited,
    publish.py still refuses.
    """
    pytest.skip(
        "Live dual-model harness deferred to first 3.b deployment dogfood."
    )
