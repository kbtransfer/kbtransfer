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


_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|$)", re.DOTALL)


def _frontmatter_range(text: str) -> tuple[int, int] | None:
    match = _FRONTMATTER_RE.match(text)
    return (match.start(), match.end()) if match else None


def _luhn_ok(digits: str) -> bool:
    # Standard Luhn: right-to-left, double every second digit, sum mod 10.
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = ord(ch) - 48  # '0' == 48
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _accept_cc_match(
    match: re.Match[str], text: str, fm_range: tuple[int, int] | None
) -> bool:
    # The CC regex matches any 13-19 digit run tolerating ` ` / `-`
    # separators — the dogfood on 2026-04-15 showed this flags things
    # like `§1, §2, ..., §14` and date concatenations. Two filters
    # narrow the match back to plausible cards:
    #   1) digits must pass the Luhn checksum (rejects most random runs);
    #   2) spans inside YAML frontmatter are skipped entirely (metadata
    #      timestamps and numeric id lists routinely hit the pattern).
    if fm_range is not None:
        fm_start, fm_end = fm_range
        if match.start() >= fm_start and match.end() <= fm_end:
            return False
    digits = "".join(c for c in match.group(0) if c.isdigit())
    if not (13 <= len(digits) <= 19):
        return False
    return _luhn_ok(digits)


@dataclass
class ScrubFinding:
    category: str
    original: str
    placeholder: str
    page: str
    # Span location within the post-substitution page text. None on legacy
    # callers that constructed findings before the v0.2 location fields.
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None


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

    Each finding carries 1-indexed line numbers and 0-indexed in-line
    character offsets pointing at the placeholder span in the
    *post-substitution* page text. Skill-driven LLM redaction
    (`examples/skills/kb-distill/`) uses these to fetch tight context
    windows instead of paraphrasing whole pages.
    """
    substitutions: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    findings: list[ScrubFinding] = []
    out: dict[str, str] = {}

    # Deterministic iteration: sort by page path for stable placeholder
    # numbering even if the caller passes a dict with a different order.
    for page_path in sorted(pages):
        text = pages[page_path]
        fm_range = _frontmatter_range(text)
        # Collect every match across all patterns first, in pre-substitution
        # coordinates; resolve overlaps by "first pattern wins" (the spec
        # ranks PII categories EMAIL > SSN > CC > PHONE > IP for a reason —
        # a 9-digit SSN should never be reclassified as a phone fragment).
        spans: list[tuple[int, int, str, str, str]] = []
        for category, prefix, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                if category == CATEGORY_CC and not _accept_cc_match(
                    match, text, fm_range
                ):
                    continue
                start, end = match.start(), match.end()
                if any(s < end and start < e for s, e, *_ in spans):
                    continue
                raw = match.group(0)
                key = (prefix, raw)
                if key not in substitutions:
                    counters[prefix] = counters.get(prefix, 0) + 1
                    substitutions[key] = f"<{prefix}_{counters[prefix]:02d}>"
                spans.append((start, end, category, prefix, substitutions[key]))
        spans.sort(key=lambda s: s[0])

        result_parts: list[str] = []
        cursor = 0
        delta = 0
        for start, end, category, _prefix, placeholder in spans:
            result_parts.append(text[cursor:start])
            new_start = start + delta
            new_end = new_start + len(placeholder)
            output_so_far = "".join(result_parts) + placeholder
            line_start = output_so_far.count("\n", 0, new_start) + 1
            line_end = output_so_far.count("\n", 0, new_end) + 1
            char_start = new_start - (output_so_far.rfind("\n", 0, new_start) + 1)
            char_end = new_end - (output_so_far.rfind("\n", 0, new_end) + 1)
            result_parts.append(placeholder)
            findings.append(
                ScrubFinding(
                    category=category,
                    original=text[start:end],
                    placeholder=placeholder,
                    page=page_path,
                    line_start=line_start,
                    line_end=line_end,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            cursor = end
            delta += len(placeholder) - (end - start)
        result_parts.append(text[cursor:])
        out[page_path] = "".join(result_parts)

    return ScrubResult(pages=out, findings=findings)
