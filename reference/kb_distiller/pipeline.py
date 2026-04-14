"""Tier-aware distillation pipeline orchestration.

Three modes map to the three locked tiers:

    mode="manual"       individual tier. Regex scrubber + publisher
                        checklist. No model inference; deterministic.

    mode="single-model" team tier. Regex scrubber + checklist of
                        extra spans the agent (driving its own LLM)
                        should review: client names, internal
                        codenames, direct quotes, monetary amounts.

    mode="dual-model"   enterprise tier. Regex scrubber + extended
                        checklist + required bias-isolated
                        adversarial-verification guidance.

The MCP server does NOT run LLM inference itself; the agent calls
kb/distill once to get the plan, performs any model-driven redaction
via kb/write on the draft pages, and then calls kb/distill again (or
kb/publish) once its policy checklist is satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kb_distiller.scrubber import ScrubFinding, ScrubResult, scrub_pages

Mode = Literal["manual", "single-model", "dual-model"]

MODE_BY_TIER: dict[str, Mode] = {
    "individual": "manual",
    "team": "single-model",
    "enterprise": "dual-model",
}

REDACTION_LEVEL_BY_MODE: dict[Mode, str] = {
    "manual": "minimal",
    "single-model": "standard",
    "dual-model": "strict",
}

_BASE_RESIDUAL_RISK_NOTES = [
    "Regex scrubber handles only well-formed PII patterns "
    "(email, phone, SSN, credit card, IPv4); obfuscated or "
    "multilingual variants may bypass detection.",
    "Stylometric fingerprints from the original author survive "
    "paraphrase passes.",
]

_EXTRA_CHECKLIST_SINGLE_MODEL = [
    "Client / customer organization names",
    "Vendor names and internal system codenames",
    "Exact monetary amounts (generalize to order-of-magnitude ranges)",
    "Employee identifiers at organization-identifying specificity",
]

_EXTRA_CHECKLIST_DUAL_MODEL = _EXTRA_CHECKLIST_SINGLE_MODEL + [
    "Direct quotes (paraphrase with >=0.75 semantic similarity)",
    "Dates narrower than quarter/year",
    "Sub-national locations (generalize to region or country)",
    "Team sizes / exact counts (bucket into bands)",
    (
        "Adversarial re-identification verification: a model from a "
        "different family than the redactor must fail to recover any "
        "redacted span above the policy's confidence threshold."
    ),
]


@dataclass
class DistillationResult:
    mode: Mode
    redaction_level: str
    pages: dict[str, str]
    categories_redacted: list[str]
    findings: list[ScrubFinding]
    checklist: list[str]
    residual_risk_notes: list[str]
    needs_agent_input: bool
    next_steps: list[str] = field(default_factory=list)

    def as_attestation_body(self, policy_id: str, policy_version: str) -> dict:
        return {
            "redaction_level": self.redaction_level,
            "policy_applied": policy_id,
            "policy_version": policy_version,
            "categories_redacted": list(self.categories_redacted),
            "residual_risk_notes": list(self.residual_risk_notes),
        }


def _mode_for(tier_or_mode: str) -> Mode:
    if tier_or_mode in MODE_BY_TIER:
        return MODE_BY_TIER[tier_or_mode]
    if tier_or_mode in ("manual", "single-model", "dual-model"):
        return tier_or_mode  # type: ignore[return-value]
    raise ValueError(f"unknown tier or mode: {tier_or_mode!r}")


def _checklist_for(mode: Mode) -> list[str]:
    base = [
        "Confirm that every wiki page included in the draft is "
        "fit for external sharing under the declared license.",
        "Review the regex scrubber findings below; acknowledge any "
        "false positives before publishing.",
    ]
    if mode == "manual":
        return base
    if mode == "single-model":
        return base + [
            f"Redact: {item}"
            for item in _EXTRA_CHECKLIST_SINGLE_MODEL
        ]
    return base + [f"Redact: {item}" for item in _EXTRA_CHECKLIST_DUAL_MODEL]


def run_pipeline(
    pages: dict[str, str],
    tier_or_mode: str,
) -> DistillationResult:
    mode: Mode = _mode_for(tier_or_mode)
    level = REDACTION_LEVEL_BY_MODE[mode]

    scrub = scrub_pages(pages)
    checklist = _checklist_for(mode)

    residual = list(_BASE_RESIDUAL_RISK_NOTES)
    if mode == "dual-model":
        residual.append(
            "Dual-model adversarial verification is declared but not "
            "automatically executed by the reference pipeline; the "
            "agent MUST drive a verifier from a different model family "
            "per the policy's adversarial_verifier_model_family_must_differ setting."
        )

    needs_agent_input = mode != "manual"
    next_steps: list[str] = []
    if needs_agent_input:
        next_steps.extend(
            [
                "Read each draft page with kb/read/0.1.",
                "Apply the checklist items above via kb/write/0.1.",
                "Call kb/distill/0.1 again to re-scrub after edits.",
                "Call kb/publish/0.1 when the checklist is satisfied.",
            ]
        )
    else:
        next_steps.append(
            "Call kb/publish/0.1 to sign and seal the draft."
        )

    return DistillationResult(
        mode=mode,
        redaction_level=level,
        pages=scrub.pages,
        categories_redacted=scrub.categories,
        findings=scrub.findings,
        checklist=checklist,
        residual_risk_notes=residual,
        needs_agent_input=needs_agent_input,
        next_steps=next_steps,
    )
