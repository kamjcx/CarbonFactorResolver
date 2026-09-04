"""Deterministic normalization and confidence calibration.

The engine uses explicit, versioned transformations and observable confidence
components. Semantic models can supply assessments, but cannot replace these
rules or introduce candidate identifiers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from .models import Candidate, RecommendationConfidence


@dataclass(frozen=True, slots=True)
class NormalizedText:
    value: str
    applied_rule_ids: tuple[str, ...]


def normalize_text(value: str | None) -> NormalizedText:
    original = str(value or "")
    current = original
    applied: list[str] = []

    normalized = unicodedata.normalize("NFKC", current)
    if normalized != current:
        applied.append("text.unicode_nfkc/v1")
        current = normalized

    normalized = current.casefold()
    if normalized != current:
        applied.append("text.casefold/v1")
        current = normalized

    normalized = re.sub(r"[（）()\[\]{}/_|,;:·—–-]+", " ", current)
    if normalized != current:
        applied.append("text.separator_space/v1")
        current = normalized

    normalized = re.sub(r"\s+", " ", current).strip()
    if normalized != current:
        applied.append("text.whitespace/v1")
        current = normalized

    return NormalizedText(current, tuple(applied))


def calibrate_confidence(candidates: Sequence[Candidate]) -> RecommendationConfidence | None:
    """Calibrate display-only resolution strength from inspectable evidence."""
    if not candidates:
        return None
    top = candidates[0]
    top_strength = top.resolution_strength or top.score
    next_strength = (candidates[1].resolution_strength or candidates[1].score) if len(candidates) > 1 else top_strength
    margin = max(0.0, top_strength - next_strength)
    margin_signal = min(1.0, margin / 0.20)
    value = round(0.65 * top_strength + 0.20 * top.evidence_coverage + 0.15 * margin_signal, 6)
    level = "high" if value >= 0.80 else "medium" if value >= 0.65 else "low"
    rationale = (
        f"top deterministic suitability score={top.score:.6f}",
        f"candidate resolution strength={top_strength:.6f}",
        f"top-to-next strength margin={margin:.6f}",
        f"evidence coverage={top.evidence_coverage:.6f}",
        "resolution strength is not a probability and does not override human approval",
    )
    return RecommendationConfidence(value, level, top.score, margin, top.evidence_coverage, rationale)
