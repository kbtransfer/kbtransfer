"""Deterministic tests for kb_distiller.family.

The family classifier is the single source of truth for the
"adversarial verifier MUST come from a different family" invariant
(spec §10). publish.py and the kb-distill-adversarial skill both
delegate to it; behavior is locked here so a typo in the prefix
table can never silently weaken the invariant.
"""

from __future__ import annotations

import pytest
from kb_distiller.family import (
    UNKNOWN_FAMILY,
    ModelFamilyError,
    assert_different_families,
    family_of,
)

# ── family_of: prefix coverage ─────────────────────────────────────────

@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("claude-opus-4-6", "anthropic"),
        ("claude-haiku-4-5", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
        ("CLAUDE-OPUS-4-6", "anthropic"),  # case-insensitive
        ("gpt-4o", "openai"),
        ("gpt-5", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("openai:gpt-4o", "openai"),  # provider-prefixed form
        ("gemini-2.0-pro", "google"),
        ("palm-2", "google"),
        ("google:gemini-2.0-pro", "google"),
        ("llama-3.1-405b", "meta"),
        ("meta:llama-3.3-70b", "meta"),
        ("mistral-large-2", "mistral"),
        ("mixtral-8x22b", "mistral"),
        ("command-r-plus", "cohere"),
        ("deepseek-v3", "deepseek"),
        ("qwen-2.5-72b", "alibaba"),
        ("grok-3", "xai"),
    ],
)
def test_family_of_known_prefixes(model_id: str, expected: str) -> None:
    assert family_of(model_id) == expected


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "unknown-model-2099",
        "phi-3-mini",  # Microsoft Phi not yet in the table
        "yi-34b",       # 01.AI Yi not yet in the table
    ],
)
def test_family_of_unknown_returns_sentinel(model_id: str) -> None:
    assert family_of(model_id) == UNKNOWN_FAMILY


def test_family_of_non_string_returns_unknown() -> None:
    assert family_of(None) == UNKNOWN_FAMILY  # type: ignore[arg-type]
    assert family_of(123) == UNKNOWN_FAMILY  # type: ignore[arg-type]


# ── assert_different_families: invariant ───────────────────────────────

def test_assert_different_families_passes_on_distinct_families() -> None:
    assert_different_families("claude-opus-4-6", "openai:gpt-4o")
    assert_different_families("openai:gpt-4o", "claude-opus-4-6")
    assert_different_families("gemini-2.0-pro", "llama-3.3-70b")


def test_assert_different_families_rejects_same_family_intra_claude() -> None:
    """The intra-Claude default verifier (Haiku) is convenient but
    does NOT satisfy the family-must-differ invariant. This is the
    case the enterprise tier policy template exists to catch."""
    with pytest.raises(ModelFamilyError, match="same family"):
        assert_different_families("claude-opus-4-6", "claude-haiku-4-5")


def test_assert_different_families_rejects_same_family_intra_openai() -> None:
    with pytest.raises(ModelFamilyError, match="same family"):
        assert_different_families("gpt-4o", "o1-preview")


def test_assert_different_families_rejects_unknown_redactor() -> None:
    """Unknown family is refusal-to-classify, NOT a wildcard. Spec §10
    requires positive evidence of family difference; an unknown
    classification cannot provide that evidence."""
    with pytest.raises(ModelFamilyError, match="cannot classify"):
        assert_different_families("custom-internal-model-v3", "claude-haiku-4-5")


def test_assert_different_families_rejects_unknown_verifier() -> None:
    with pytest.raises(ModelFamilyError, match="cannot classify"):
        assert_different_families("claude-opus-4-6", "custom-verifier-v1")
