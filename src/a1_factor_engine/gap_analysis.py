"""Structured candidate-gap analysis for Proxy Resolution V1."""

from __future__ import annotations

from .matching import normalize_text
from .models import (
    Candidate,
    GapType,
    LinkStrategy,
    NormalizedActivity,
    ResolutionGap,
    RouterType,
)
from .units import is_mass_unit


def _norm(value: object) -> str:
    return normalize_text(str(value or "")).value


def _different(target: object, candidate: object) -> bool:
    return bool(_norm(target) and _norm(target) != _norm(candidate))


def _material_terms(value: str | None) -> set[str]:
    normalized = _norm(value)
    latin = {part for part in normalized.split() if len(part) >= 3}
    cjk = "".join(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    return latin | {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}


def analyze_candidate_gaps(
    activity: NormalizedActivity, candidate: Candidate
) -> tuple[ResolutionGap, ...]:
    """Describe differences without deciding whether a candidate is usable."""
    source = candidate.source
    gaps: list[ResolutionGap] = []

    def add(
        gap_type: GapType,
        target: object,
        observed: object,
        severity: float,
        reason: str,
        *routers: RouterType,
    ) -> None:
        gaps.append(ResolutionGap(
            gap_id=f"{candidate.candidate_id}:{gap_type.value}",
            candidate_id=candidate.candidate_id,
            gap_type=gap_type,
            target_value=None if target is None else str(target),
            candidate_value=None if observed is None else str(observed),
            severity=severity,
            reason=reason,
            resolvable_by=tuple(routers),
        ))

    if source.factor_unit.casefold().replace(" ", "") != activity.target_factor_unit.casefold().replace(" ", ""):
        add(
            GapType.UNIT_SCALE, activity.target_factor_unit, source.factor_unit, 0.1,
            "factor unit requires deterministic scale conversion", RouterType.UNIT_SCALE,
        )
    if is_mass_unit(activity.original_quantity_unit) and _norm(activity.original_quantity_unit) != "kg":
        add(
            GapType.UNIT_SCALE, "kg", activity.original_quantity_unit, 0.1,
            "activity quantity requires deterministic mass-unit conversion", RouterType.UNIT_SCALE,
        )
    if activity.quantity_kg is None:
        add(
            GapType.REFERENCE_FLOW, "mass", activity.original_quantity_unit, 1.0,
            "activity reference flow is not a mass unit", RouterType.REFERENCE_FLOW,
        )
    if _different(activity.production_process, source.production_process):
        add(
            GapType.PROCESS_VARIANT, activity.production_process, source.production_process, 0.8,
            "target and reference production routes differ", RouterType.PROCESS_VARIANT,
        )
    elif activity.production_process and not source.production_process:
        add(
            GapType.PROCESS_VARIANT, activity.production_process, None, 0.5,
            "reference production route is unspecified", RouterType.PROCESS_VARIANT,
        )
    if _different(activity.composition, source.composition):
        add(
            GapType.GRADE_COMPOSITION, activity.composition, source.composition, 0.7,
            "target and reference grade or composition differ", RouterType.GRADE_COMPOSITION,
        )
    elif activity.composition and not source.composition:
        add(
            GapType.GRADE_COMPOSITION, activity.composition, None, 0.5,
            "reference grade or composition is unspecified", RouterType.GRADE_COMPOSITION,
        )

    strategy = source.metadata.get("match_strategy", "")
    if candidate.origin.value == "proxy" or strategy == LinkStrategy.RELATED.value:
        target_terms = _material_terms(activity.canonical_name)
        source_terms = _material_terms(source.material_name)
        has_same_material_resolution = any(
            gap.gap_type in {GapType.PROCESS_VARIANT, GapType.GRADE_COMPOSITION}
            for gap in gaps
        )
        if candidate.origin.value == "proxy" or not target_terms & source_terms or not has_same_material_resolution:
            add(
                GapType.MATERIAL_ABSENT, activity.canonical_name, source.material_name, 1.0,
                "target material is absent and this record is a material proxy", RouterType.CLASS_AWARE_PROXY,
            )
    if _different(activity.boundary, source.boundary):
        add(GapType.BOUNDARY, activity.boundary, source.boundary, 0.7, "system boundaries differ")
    elif activity.boundary and not source.boundary:
        add(GapType.BOUNDARY, activity.boundary, None, 0.4, "reference boundary is unspecified")
    if _different(activity.geography, source.geography):
        add(GapType.GEOGRAPHY, activity.geography, source.geography, 0.4, "geographies differ")
    elif activity.geography and not source.geography:
        add(GapType.GEOGRAPHY, activity.geography, None, 0.3, "reference geography is unspecified")
    if activity.year is not None and source.year is not None and activity.year != source.year:
        add(GapType.TEMPORAL, activity.year, source.year, min(1.0, abs(activity.year - source.year) / 10), "reference year differs")
    elif activity.year is not None and source.year is None:
        add(GapType.TEMPORAL, activity.year, None, 0.3, "reference year is unspecified")
    if _different(activity.product_form, source.product_form):
        add(GapType.FORM, activity.product_form, source.product_form, 0.5, "product forms differ")
    elif activity.product_form and not source.product_form:
        add(GapType.FORM, activity.product_form, None, 0.3, "reference product form is unspecified")
    return tuple(gaps)


PRIMARY_GAPS = frozenset({
    GapType.REFERENCE_FLOW,
    GapType.PROCESS_VARIANT,
    GapType.GRADE_COMPOSITION,
    GapType.MATERIAL_ABSENT,
})


def directly_usable(gaps: tuple[ResolutionGap, ...]) -> bool:
    return not any(gap.gap_type in PRIMARY_GAPS for gap in gaps)
