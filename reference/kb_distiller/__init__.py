"""Tier-aware distillation pipeline: manual / single-model / dual-model adversarial."""

from __future__ import annotations

__version__ = "0.1.0"

from kb_distiller.family import (
    UNKNOWN_FAMILY,
    ModelFamilyError,
    assert_different_families,
    family_of,
)
from kb_distiller.pipeline import (
    MODE_BY_TIER,
    REDACTION_LEVEL_BY_MODE,
    DistillationResult,
    Mode,
    run_pipeline,
)
from kb_distiller.scrubber import ScrubFinding, ScrubResult, scrub_pages

__all__ = [
    "MODE_BY_TIER",
    "REDACTION_LEVEL_BY_MODE",
    "UNKNOWN_FAMILY",
    "DistillationResult",
    "Mode",
    "ModelFamilyError",
    "ScrubFinding",
    "ScrubResult",
    "assert_different_families",
    "family_of",
    "run_pipeline",
    "scrub_pages",
]
