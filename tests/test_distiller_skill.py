"""CI invariants for the kb-distill skill (Phase 3.a).

These tests are deterministic — no LLM calls. They cover the
server-side enablers the skill depends on:

- ScrubFinding now carries 1-indexed line + 0-indexed in-line char
  spans, computed against the *post-substitution* page text.
- build_redaction accepts an optional llm_assisted_by block (additive,
  preserves the v0.1.1 amendment C1 invariant on residual_risk_notes).
- publish.py reads .distill-report.json's llm_assisted_by and passes
  it through to the attestation.

The actual LLM-driven rewrite loop the skill encodes lives in
examples/skills/kb-distill/SKILL.md; the smoke-test for that loop is
the optional adversarial canary in
tests/adversarial/test_distiller_skill_canary.py (skipped unless
KBTRANSFER_LLM_TESTS=1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kb_distiller.scrubber import scrub_pages
from kb_pack.attestation import AttestationError, build_redaction

# ── ScrubFinding location fields ───────────────────────────────────────

def test_scrub_finding_locations_point_at_placeholder_in_output() -> None:
    """For every finding, the recorded span must select exactly the
    placeholder text in the post-substitution page."""
    pages = {
        "p.md": "Line 1 plain.\nContact me at me@example.com today.\nThird line.",
    }
    result = scrub_pages(pages)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.line_start is not None and f.char_start is not None
    out_lines = result.pages["p.md"].split("\n")
    line = out_lines[f.line_start - 1]  # line_start is 1-indexed
    assert line[f.char_start : f.char_end] == f.placeholder


def test_scrub_finding_locations_handle_multiple_findings_per_page() -> None:
    pages = {
        "p.md": (
            "Header line.\n"
            "Email me@example.com or call 555-123-4567.\n"
            "Backup: alt@example.com.\n"
        ),
    }
    result = scrub_pages(pages)
    assert len(result.findings) >= 3
    out = result.pages["p.md"]
    for f in result.findings:
        line = out.split("\n")[f.line_start - 1]
        assert line[f.char_start : f.char_end] == f.placeholder


def test_scrub_finding_locations_are_post_substitution() -> None:
    """A long PII string substituted into a short placeholder shifts
    later spans leftward; locations must reflect the shifted output."""
    pages = {
        "p.md": "Card 4111-1111-1111-1111 then ip 10.0.0.42 again.\n",
    }
    result = scrub_pages(pages)
    out = result.pages["p.md"]
    # Both findings must select their placeholders in the OUTPUT text.
    for f in result.findings:
        line = out.split("\n")[f.line_start - 1]
        assert line[f.char_start : f.char_end] == f.placeholder


def test_scrub_finding_locations_cross_pages_independent() -> None:
    """Locations are per-page; placeholder numbering is global, but
    the line/char spans reset for each page."""
    pages = {
        "a.md": "first email me@example.com.",
        "b.md": "second email you@example.com.",
    }
    result = scrub_pages(pages)
    by_page = {f.page: f for f in result.findings}
    for page, f in by_page.items():
        line = result.pages[page].split("\n")[f.line_start - 1]
        assert line[f.char_start : f.char_end] == f.placeholder


# ── build_redaction llm_assisted_by passthrough ────────────────────────

def _redaction_kwargs() -> dict:
    return {
        "pack_ref": "demo.pack@1.0.0",
        "content_root": "sha256:" + "0" * 64,
        "issuer": "did:web:example.com",
        "redaction_level": "standard",
        "policy_id": "kbtransfer-single-model",
        "policy_version": "kbtransfer/0.1",
        "residual_risk_notes": ["Stylometric fingerprints survive paraphrase."],
        "categories_redacted": ["identity.person.email"],
    }


def test_build_redaction_omits_llm_assisted_by_when_not_passed() -> None:
    doc = build_redaction(**_redaction_kwargs())
    assert "llm_assisted_by" not in doc


def test_build_redaction_includes_llm_assisted_by_when_passed() -> None:
    block = {
        "model": "claude-opus-4-6",
        "mode": "single-model",
        "skill": "kb-distill@0.1",
        "regex_loop_iterations": 2,
        "residual_review_pass2": True,
        "started_at": "2026-04-15T13:42:00Z",
        "completed_at": "2026-04-15T13:42:47Z",
        "pages_rewritten": 4,
    }
    doc = build_redaction(**_redaction_kwargs(), llm_assisted_by=block)
    assert doc["llm_assisted_by"] == block


def test_build_redaction_still_enforces_residual_risk_notes() -> None:
    """Adding llm_assisted_by must not soften the C1 invariant."""
    kwargs = _redaction_kwargs()
    kwargs["residual_risk_notes"] = []
    with pytest.raises(AttestationError):
        build_redaction(**kwargs, llm_assisted_by={"model": "x"})


def test_build_redaction_copies_llm_assisted_by_dict() -> None:
    """Mutating the input dict after build must not mutate the
    attestation — dict() copy semantics."""
    block = {"model": "claude-opus-4-6", "mode": "single-model"}
    doc = build_redaction(**_redaction_kwargs(), llm_assisted_by=block)
    block["model"] = "tampered"
    assert doc["llm_assisted_by"]["model"] == "claude-opus-4-6"


# ── publish.py reads llm_assisted_by from .distill-report.json ─────────

def test_publish_threads_llm_assisted_by_from_report(tmp_path: Path) -> None:
    """publish._populate_attestations should plumb the report's
    llm_assisted_by into the redaction attestation file on disk."""
    from kb_mcp_server.tools.publish import _populate_attestations

    draft = tmp_path / "drafts" / "demo.pack"
    (draft / "pages").mkdir(parents=True)
    (draft / "attestations").mkdir(parents=True)
    (draft / "pages" / "01-overview.md").write_text("Hello world.\n", encoding="utf-8")
    (draft / "pack.manifest.yaml").write_text(
        "pack_id: demo.pack\nversion: 1.0.0\nlicense: { spdx: Apache-2.0 }\n",
        encoding="utf-8",
    )
    report = {
        "mode": "single-model",
        "redaction_level": "standard",
        "categories_redacted": ["identity.person.email"],
        "residual_risk_notes": ["Stylometric fingerprints survive."],
        "llm_assisted_by": {
            "model": "claude-opus-4-6",
            "mode": "single-model",
            "skill": "kb-distill@0.1",
            "regex_loop_iterations": 1,
            "residual_review_pass2": True,
            "started_at": "2026-04-15T13:42:00Z",
            "completed_at": "2026-04-15T13:42:13Z",
            "pages_rewritten": 1,
        },
    }
    (draft / ".distill-report.json").write_text(json.dumps(report), encoding="utf-8")

    manifest = {
        "pack_id": "demo.pack",
        "version": "1.0.0",
        "license": {"spdx": "Apache-2.0"},
    }
    policy = {
        "publisher": {"distiller_mode": "single-model"},
        "policy_version": "kbtransfer/0.1",
    }
    _populate_attestations(
        draft,
        manifest=manifest,
        policy=policy,
        composite_score=0.0,
        publisher_id="did:web:example.com",
    )

    written = json.loads((draft / "attestations" / "redaction.json").read_text())
    assert written["llm_assisted_by"]["model"] == "claude-opus-4-6"
    assert written["llm_assisted_by"]["regex_loop_iterations"] == 1
    assert written["llm_assisted_by"]["residual_review_pass2"] is True


def test_publish_omits_llm_assisted_by_when_report_lacks_it(tmp_path: Path) -> None:
    """Pre-skill (manual mode) drafts have no llm_assisted_by key.
    publish must not emit a stub block — absence is meaningful."""
    from kb_mcp_server.tools.publish import _populate_attestations

    draft = tmp_path / "drafts" / "demo.pack"
    (draft / "pages").mkdir(parents=True)
    (draft / "attestations").mkdir(parents=True)
    (draft / "pages" / "01.md").write_text("hi\n", encoding="utf-8")
    (draft / "pack.manifest.yaml").write_text(
        "pack_id: demo.pack\nversion: 1.0.0\n", encoding="utf-8"
    )
    report = {
        "mode": "manual",
        "redaction_level": "minimal",
        "categories_redacted": [],
        "residual_risk_notes": ["Manual review only; no LLM pass."],
    }
    (draft / ".distill-report.json").write_text(json.dumps(report), encoding="utf-8")

    _populate_attestations(
        draft,
        manifest={"pack_id": "demo.pack", "version": "1.0.0"},
        policy={"publisher": {"distiller_mode": "manual"}},
        composite_score=0.0,
        publisher_id="did:web:example.com",
    )

    written = json.loads((draft / "attestations" / "redaction.json").read_text())
    assert "llm_assisted_by" not in written
