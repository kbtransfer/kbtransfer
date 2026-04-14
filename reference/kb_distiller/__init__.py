"""Tier-aware distillation pipeline: manual / single-model / dual-model adversarial."""

from __future__ import annotations

__version__ = "0.1.0"

from kb_distiller.pipeline import (
    MODE_BY_TIER,
    REDACTION_LEVEL_BY_MODE,
    DistillationResult,
    Mode,
    run_pipeline,
)
from kb_distiller.scrubber import ScrubFinding, ScrubResult, scrub_pages

__all__ = [
    "DistillationResult",
    "MODE_BY_TIER",
    "Mode",
    "REDACTION_LEVEL_BY_MODE",
    "ScrubFinding",
    "ScrubResult",
    "run_pipeline",
    "scrub_pages",
]
