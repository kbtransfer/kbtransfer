"""Model-family identification for the dual-model adversarial pipeline.

Spec §10 (and the enterprise-tier policy template) requires that the
adversarial verifier model belong to a *different family* than the
redactor model — the bias-isolation premise of the dual-model
distillation patent claim. A "family" here is the upstream training
lineage: two `claude-*` checkpoints are the same family even if one
is Opus and the other Haiku; a `gpt-*` and a `claude-*` are different.

This module is the single source of truth for that classification.
The check is deterministic and offline; no network I/O. New families
are added by extending `_FAMILY_PREFIXES` — that is the entire
extension point.

Used by:
- `kb_mcp_server/tools/publish.py` to refuse to seal a redaction
  attestation whose `adversarial_verification` block names two
  same-family models when policy demands a difference.
- `examples/skills/kb-distill-adversarial/` to pre-flight the
  publisher's `VERIFIER_MODEL` env override before running the
  verifier loop.
"""

from __future__ import annotations

# Maps a model-id prefix (case-insensitive) to its family name. Order
# matters: the first matching prefix wins, so put more-specific
# prefixes ahead of more-general ones if they ever overlap.
#
# Model ids may also use a `provider:model` form (e.g.
# `openai:gpt-4o`); the prefix lookup walks both the raw id and the
# part after `:` if present, so either form classifies correctly.
_FAMILY_PREFIXES: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("gemini", "google"),
    ("palm", "google"),
    ("llama", "meta"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("command", "cohere"),
    ("deepseek", "deepseek"),
    ("qwen", "alibaba"),
    ("grok", "xai"),
]

UNKNOWN_FAMILY = "unknown"


class ModelFamilyError(ValueError):
    """Raised when a model-family invariant is violated."""


def family_of(model_id: str) -> str:
    """Return the family name for a model id.

    Returns `UNKNOWN_FAMILY` for ids that do not match any known
    prefix. Callers MUST treat unknown as a refusal-to-classify, not
    a wildcard — `assert_different_families` rejects unknown on either
    side rather than letting it satisfy the constraint.
    """
    if not isinstance(model_id, str) or not model_id:
        return UNKNOWN_FAMILY
    candidates = [model_id.lower()]
    if ":" in model_id:
        # Tolerate provider:model form ("openai:gpt-4o" → "gpt-4o").
        candidates.append(model_id.split(":", 1)[1].lower())
    for candidate in candidates:
        for prefix, family in _FAMILY_PREFIXES:
            if candidate.startswith(prefix):
                return family
    return UNKNOWN_FAMILY


def assert_different_families(redactor_model: str, verifier_model: str) -> None:
    """Raise if redactor and verifier appear to be from the same family.

    Symmetric — order does not matter. Unknown family on either side
    is treated as a failure (refusal-to-classify), preserving the
    bias-isolation invariant against future models we have not yet
    catalogued.
    """
    r_family = family_of(redactor_model)
    v_family = family_of(verifier_model)
    if r_family == UNKNOWN_FAMILY or v_family == UNKNOWN_FAMILY:
        unknown = redactor_model if r_family == UNKNOWN_FAMILY else verifier_model
        raise ModelFamilyError(
            f"cannot classify model family for {unknown!r}; add its prefix to "
            "kb_distiller.family._FAMILY_PREFIXES before relying on the "
            "adversarial_verifier_model_family_must_differ policy."
        )
    if r_family == v_family:
        raise ModelFamilyError(
            f"redactor ({redactor_model!r}, family={r_family!r}) and "
            f"verifier ({verifier_model!r}, family={v_family!r}) are the "
            "same family; policy requires different families for "
            "adversarial verification (spec §10)."
        )
