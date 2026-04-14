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
