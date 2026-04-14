"""Deterministic regex-based PII scrubber.

This is the auto-redaction layer every tier starts with. It handles
patterns that are objectively PII regardless of domain:

    identity.person.email       me@example.com
    identity.person.phone       +1 (555) 123-4567 / (555) 123-4567
    identity.person.ssn         123-45-6789
    identity.financial.cc       4111 1111 1111 1111
    technical.internal.ip       10.0.0.42

Placeholders are stable across a single distillation: the third
email seen becomes `<EMAIL_03>` everywhere, including on earlier
pages. This preserves cross-page consistency (spec §11, pseudonym
scope "pack").

Agents (and enterprise-tier dual-model verifiers) are expected to
catch the harder spans — client names, internal codenames,
paraphrased quotes — on top of what this scrubber finds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORY_EMAIL = "identity.person.email"
CATEGORY_PHONE = "identity.person.phone"
CATEGORY_SSN = "identity.person.ssn"
CATEGORY_CC = "identity.financial.cc"
CATEGORY_IP = "technical.internal.ip"

_PATTERNS = [
    (
        CATEGORY_EMAIL,
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        CATEGORY_SSN,
        "SSN",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ),
    (
        CATEGORY_CC,
        "CC",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    ),
    (
        CATEGORY_PHONE,
        "PHONE",
        re.compile(
            r"(?:\+?\d{1,3}[ \-.]?)?(?:\(\d{2,4}\)|\d{2,4})[ \-.]?\d{2,4}[ \-.]?\d{2,4}(?:[ \-.]?\d{2,4})?"
        ),
    ),
    (
        CATEGORY_IP,
        "IP",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b"
        ),
    ),
]


@dataclass
class ScrubFinding:
    category: str
    original: str
    placeholder: str
    page: str


@dataclass
class ScrubResult:
    pages: dict[str, str]
    findings: list[ScrubFinding] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        return sorted({f.category for f in self.findings})


def scrub_pages(pages: dict[str, str]) -> ScrubResult:
    """Scrub a mapping of page_path -> markdown text.

    Returns the transformed mapping alongside a list of findings.
    Placeholders (e.g. `<EMAIL_01>`) are stable: if the same email
    appears on two pages it gets the same placeholder in both.
    """
    substitutions: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    findings: list[ScrubFinding] = []
    out: dict[str, str] = {}

    # Deterministic iteration: sort by page path for stable placeholder
    # numbering even if the caller passes a dict with a different order.
    for page_path in sorted(pages):
        text = pages[page_path]
        for category, prefix, pattern in _PATTERNS:
            def _repl(match: re.Match[str]) -> str:
                raw = match.group(0)
                key = (prefix, raw)
                if key not in substitutions:
                    counters[prefix] = counters.get(prefix, 0) + 1
                    substitutions[key] = f"<{prefix}_{counters[prefix]:02d}>"
                placeholder = substitutions[key]
                findings.append(
                    ScrubFinding(
                        category=category,
                        original=raw,
                        placeholder=placeholder,
                        page=page_path,
                    )
                )
                return placeholder

            text = pattern.sub(_repl, text)
        out[page_path] = text

    return ScrubResult(pages=out, findings=findings)
