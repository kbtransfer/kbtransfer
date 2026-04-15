"""Tests for the kb_distiller tier-aware redaction pipeline."""

from __future__ import annotations

from kb_distiller import MODE_BY_TIER, run_pipeline, scrub_pages


def test_scrub_pages_redacts_email_consistently() -> None:
    pages = {
        "a.md": "Contact alice@example.com for details.",
        "b.md": "Escalate to alice@example.com and bob@example.com.",
    }
    result = scrub_pages(pages)
    # Two distinct emails -> two distinct placeholders.
    assert "<EMAIL_01>" in result.pages["a.md"]
    # Alice's address is the first seen, so it keeps <EMAIL_01> on page b too.
    assert result.pages["b.md"].count("<EMAIL_01>") == 1
    assert "<EMAIL_02>" in result.pages["b.md"]
    assert "identity.person.email" in result.categories


def test_scrub_pages_handles_multiple_pii_categories() -> None:
    pages = {
        "only.md": (
            "Call 555-123-4567 or email foo@example.com.\n"
            "SSN: 123-45-6789. Card: 4111 1111 1111 1111."
        ),
    }
    result = scrub_pages(pages)
    cats = set(result.categories)
    assert "identity.person.email" in cats
    assert "identity.person.ssn" in cats
    assert "identity.financial.cc" in cats


def test_scrubber_does_not_flag_section_numbers() -> None:
    # The 2026-04-15 full-cycle dogfood flagged `§1, §2, ..., §14` and
    # date concatenations as credit cards because the regex accepts any
    # 13-19 digit run. Luhn + frontmatter filtering must kill these.
    pages = {
        "sections.md": "See §1, §2, §3, §4, §5, §6, §7, §8, §9, §10, §11, §12, §13, §14 for details.",
        "dates.md": (
            "Timeline: 2026-04-14, 2026-04-15, 2026-04-16, 2026-04-17, "
            "2026-04-18 rollout window."
        ),
        "ids.md": "Issue ids 1-2-3-4-5-6-7-8-9-10-11-12-13 were all merged.",
    }
    result = scrub_pages(pages)
    assert "identity.financial.cc" not in result.categories, result.categories
    for finding in result.findings:
        assert finding.category != "identity.financial.cc"


def test_scrubber_ignores_digits_in_frontmatter() -> None:
    # A pack-manifest-style frontmatter block may contain numeric lists
    # that coincidentally produce ≥13 sequential digits. The body of the
    # page — where real PII lives — must still be scanned normally.
    # The frontmatter below includes a deliberately Luhn-valid string
    # (4111111111111111, the classic Visa test) so this test fails if the
    # Luhn check is the only filter and the frontmatter exclusion is not
    # actually being applied.
    page = (
        "---\n"
        "pack_id: example.sections\n"
        "test_card_placeholder: 4111111111111111\n"
        "version: 1-2-3-4-5-6-7-8-9-10-11-12-13\n"
        "---\n\n"
        "# Body\n\n"
        "Legitimate reference card: 4111 1111 1111 1111.\n"
    )
    result = scrub_pages({"p.md": page})
    cc_findings = [f for f in result.findings if f.category == "identity.financial.cc"]
    assert len(cc_findings) == 1
    assert cc_findings[0].original == "4111 1111 1111 1111"


def test_scrubber_rejects_non_luhn_digit_runs() -> None:
    # Random 16-digit string that is NOT Luhn-valid must not be
    # classified as a credit card.
    pages = {"p.md": "Reference id 1234567890123456 in the invoice system."}
    result = scrub_pages(pages)
    assert "identity.financial.cc" not in result.categories


def test_run_pipeline_individual_tier_is_manual_mode() -> None:
    result = run_pipeline({"p.md": "Hi me@example.com"}, tier_or_mode="individual")
    assert result.mode == "manual"
    assert result.redaction_level == "minimal"
    assert result.needs_agent_input is False
    # Manual checklist should NOT include team/enterprise-only redaction items.
    assert not any("codename" in item.lower() for item in result.checklist)


def test_run_pipeline_team_tier_asks_agent_for_model_pass() -> None:
    result = run_pipeline({"p.md": "Acme is our top client."}, tier_or_mode="team")
    assert result.mode == "single-model"
    assert result.redaction_level == "standard"
    assert result.needs_agent_input is True
    assert any("codename" in item.lower() or "client" in item.lower()
               for item in result.checklist)


def test_run_pipeline_enterprise_tier_requires_adversarial() -> None:
    result = run_pipeline({"p.md": "Internal project Kraken kicks off Q3."},
                          tier_or_mode="enterprise")
    assert result.mode == "dual-model"
    assert result.redaction_level == "strict"
    assert any("adversarial" in item.lower() for item in result.checklist)
    assert any("different model family" in note.lower()
               for note in result.residual_risk_notes)


def test_mode_by_tier_covers_all_three_tiers() -> None:
    assert set(MODE_BY_TIER.keys()) == {"individual", "team", "enterprise"}
