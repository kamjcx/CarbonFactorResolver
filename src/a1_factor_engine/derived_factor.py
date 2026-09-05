"""Helpers for provenance-preserving derived factor candidates."""

from __future__ import annotations

from dataclasses import replace

from .models import (
    Candidate,
    DerivedFactorCandidate,
    FactorKind,
    FactorSourceType,
    ResolutionType,
    ResultTier,
    TransformationStep,
)
from .units import convert_factor, parse_factor_unit

TYPE_PRIORITY = {
    ResolutionType.DIRECT_EXACT: 0,
    ResolutionType.DIRECT_ALIAS: 1,
    ResolutionType.UNIT_CONVERTED: 2,
    ResolutionType.REFERENCE_FLOW_CONVERTED: 3,
    ResolutionType.PROCESS_ADJUSTED: 4,
    ResolutionType.GRADE_EXACT_ANCHOR: 4,
    ResolutionType.GRADE_INTERPOLATED: 5,
    ResolutionType.GRADE_ADJUSTED: 5,
    ResolutionType.GRADE_PROXY: 6,
    ResolutionType.UNADJUSTED_PROCESS_PROXY: 7,
    ResolutionType.CLASS_TECHNICAL_PROXY: 8,
    ResolutionType.CLASS_GENERIC_PROXY: 9,
}

SOURCE_QUALITY = {
    FactorSourceType.SUPPLIER: 0.55,
    FactorSourceType.LOCAL_DATABASE: 0.9,
    FactorSourceType.EPD: 0.9,
    FactorSourceType.LITERATURE: 0.7,
    FactorSourceType.EXTERNAL_DATABASE: 0.75,
}


def application_total_kgco2e(
    factor_value: float,
    factor_unit: str,
    resolved_activity_value: float,
    resolved_activity_unit: str,
) -> float:
    """Apply a factor to denominator-aligned activity and return kgCO2e.

    ``resolved_activity_value`` is authoritative for factor application. The
    compatibility field ``resolved_quantity_kg`` must never be multiplied by a
    per-tonne or per-gram factor directly.
    """

    parsed = parse_factor_unit(factor_unit)
    denominator = parsed.activity_unit.canonical_unit
    if resolved_activity_unit != denominator:
        raise ValueError(
            "resolved activity must be denominator-aligned with the factor unit"
        )
    factor_kgco2e = convert_factor(
        factor_value,
        factor_unit,
        f"kgCO2e/{denominator}",
    )
    return factor_kgco2e * resolved_activity_value


def source_quality(candidate: Candidate) -> float:
    """Deterministic quality signal based on evidence, never source label alone."""

    base = SOURCE_QUALITY.get(candidate.source.source_type, 0.6)
    if candidate.source.source_type != FactorSourceType.SUPPLIER:
        return base
    metadata = candidate.source.metadata
    verified = str(metadata.get("verified", "")).casefold() in {"true", "1", "yes"}
    audited = str(metadata.get("audited", "")).casefold() in {"true", "1", "yes"}
    documented = bool(candidate.source.citation and candidate.source.locator and candidate.source.boundary)
    return min(0.95, base + 0.15 * verified + 0.15 * audited + 0.10 * documented)


def resolution_strength(
    candidate: Candidate,
    *,
    step_count: int | None = None,
    assumption_count: int | None = None,
) -> float:
    steps = len(candidate.transformation_steps) if step_count is None else step_count
    assumptions = len(candidate.assumptions) if assumption_count is None else assumption_count
    quality = source_quality(candidate)
    derivation_signal = max(0.0, 1.0 - 0.12 * steps - 0.06 * assumptions)
    gap_penalty = min(0.25, 0.05 * sum(gap.severity for gap in candidate.gaps))
    return round(min(1.0, max(0.0,
        0.45 * candidate.score
        + 0.30 * candidate.evidence_coverage
        + 0.15 * quality
        + 0.10 * derivation_signal
        - gap_penalty
    )), 6)


def tier_for(candidate: Candidate) -> ResultTier:
    if any(item.startswith("formal_admission_incomplete:") for item in candidate.limitations):
        return ResultTier.REFERENCE_ONLY
    if (
        candidate.source.factor_kind not in {
            FactorKind.LIFECYCLE_FACTOR,
            FactorKind.EPD_INDICATOR,
            FactorKind.DERIVED_PROXY_FACTOR,
            FactorKind.ENERGY_FACTOR,
            FactorKind.COMBUSTION_FACTOR,
            FactorKind.TRANSPORT_FACTOR,
        }
        or candidate.source.indicator not in {"GWP-total", "gwp-total"}
    ):
        return ResultTier.REFERENCE_ONLY
    if candidate.resolution_type in {ResolutionType.DIRECT_EXACT, ResolutionType.DIRECT_ALIAS, ResolutionType.UNIT_CONVERTED}:
        if any(gap.severity >= 0.5 for gap in candidate.gaps):
            return ResultTier.USABLE_WITH_ASSUMPTIONS
        return ResultTier.PRIMARY_RECOMMENDATION
    if candidate.resolution_type == ResolutionType.GRADE_EXACT_ANCHOR:
        return ResultTier.PRIMARY_RECOMMENDATION
    if candidate.resolution_type in {
        ResolutionType.REFERENCE_FLOW_CONVERTED,
        ResolutionType.PROCESS_ADJUSTED,
        ResolutionType.GRADE_INTERPOLATED,
        ResolutionType.GRADE_ADJUSTED,
        ResolutionType.CLASS_TECHNICAL_PROXY,
    }:
        return ResultTier.USABLE_WITH_ASSUMPTIONS
    return ResultTier.REFERENCE_ONLY


def finalize_candidate(candidate: Candidate, *, min_score: float | None = None) -> Candidate:
    tier = tier_for(candidate)
    if min_score is not None and candidate.score < min_score:
        tier = ResultTier.REFERENCE_ONLY
    tier_cap = str(candidate.source.metadata.get("result_tier_cap", "")).strip()
    limitations = candidate.limitations
    if tier_cap == ResultTier.REFERENCE_ONLY.value:
        tier = ResultTier.REFERENCE_ONLY
        limitations = tuple(dict.fromkeys((
            *limitations,
            "source governance caps this candidate at REFERENCE_ONLY",
        )))
    strength = resolution_strength(candidate)
    return replace(
        candidate,
        result_tier=tier,
        resolution_strength=strength,
        limitations=limitations,
    )


def derive_candidate(
    base: Candidate,
    *,
    candidate_id: str,
    resolution_type: ResolutionType,
    factor_value: float | None = None,
    steps: tuple[TransformationStep, ...] = (),
    parameter_ids: tuple[str, ...] = (),
    base_source_ids: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    resolved_activity_value: float | None = None,
    resolved_activity_unit: str | None = None,
    activity_dimension: str | None = None,
    resolved_quantity_kg: float | None = None,
    total_emissions_kgco2e: float | None = None,
) -> Candidate:
    effective_factor = base.factor_value if factor_value is None else factor_value
    effective_quantity = (
        resolved_quantity_kg
        if resolved_quantity_kg is not None
        else base.resolved_quantity_kg
    )
    effective_activity = (
        resolved_activity_value
        if resolved_activity_value is not None else base.resolved_activity_value
    )
    effective_activity_unit = resolved_activity_unit or base.resolved_activity_unit
    effective_dimension = activity_dimension or base.activity_dimension
    if total_emissions_kgco2e is not None:
        effective_total = total_emissions_kgco2e
    elif effective_activity is not None:
        if effective_activity_unit is None:
            raise ValueError("resolved activity unit is required for factor application")
        effective_total = application_total_kgco2e(
            effective_factor,
            base.factor_unit,
            effective_activity,
            effective_activity_unit,
        )
    elif effective_quantity is not None:
        effective_total = (
            convert_factor(effective_factor, base.factor_unit, "kgCO2e/kg")
            * effective_quantity
        )
    else:
        effective_total = None
    candidate = replace(
        base,
        candidate_id=candidate_id,
        factor_value=effective_factor,
        resolution_type=resolution_type,
        transformation_steps=base.transformation_steps + steps,
        parameter_evidence_ids=tuple(dict.fromkeys(base.parameter_evidence_ids + parameter_ids)),
        base_source_ids=tuple(dict.fromkeys(base.base_source_ids + (base.source.source_id,) + base_source_ids)),
        reasons=base.reasons + reasons,
        limitations=tuple(dict.fromkeys(base.limitations + limitations)),
        assumptions=tuple(dict.fromkeys(base.assumptions + assumptions)),
        warnings=tuple(dict.fromkeys(base.warnings + warnings)),
        resolved_activity_value=effective_activity,
        resolved_activity_unit=effective_activity_unit,
        activity_dimension=effective_dimension,
        resolved_quantity_kg=effective_quantity,
        total_emissions_kgco2e=effective_total,
    )
    return finalize_candidate(candidate)


def expected_total_emissions(candidate: Candidate) -> float | None:
    """Return the total implied by a candidate's normalized factor and quantity."""

    if candidate.resolved_activity_value is not None:
        if candidate.resolved_activity_unit is None:
            raise ValueError("resolved activity unit is required for factor application")
        return application_total_kgco2e(
            candidate.factor_value,
            candidate.factor_unit,
            candidate.resolved_activity_value,
            candidate.resolved_activity_unit,
        )
    if candidate.resolved_quantity_kg is None:
        return None
    if parse_factor_unit(candidate.factor_unit).activity_unit.dimension.value != "MASS":
        raise ValueError(
            "resolved_quantity_kg compatibility fallback requires a mass factor"
        )
    return (
        convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        * candidate.resolved_quantity_kg
    )


def to_derived(candidate: Candidate) -> DerivedFactorCandidate:
    return DerivedFactorCandidate(
        candidate_id=candidate.candidate_id,
        resolution_type=candidate.resolution_type,
        base_source_ids=candidate.base_source_ids or (candidate.source.source_id,),
        parameter_evidence_ids=candidate.parameter_evidence_ids,
        transformation_steps=candidate.transformation_steps,
        factor_value=candidate.factor_value,
        factor_unit=candidate.factor_unit,
        boundary=candidate.source.boundary,
        geography=candidate.source.geography,
        year=candidate.source.year,
        reasons=candidate.reasons,
        limitations=candidate.limitations,
        evidence_coverage=candidate.evidence_coverage,
        resolution_strength=candidate.resolution_strength,
        provenance_lineage=tuple(dict.fromkeys((
            *candidate.base_source_ids,
            *candidate.parameter_evidence_ids,
            *(step.formula_id for step in candidate.transformation_steps),
        ))),
        assumptions=candidate.assumptions,
        warnings=candidate.warnings,
        resolved_activity_value=candidate.resolved_activity_value,
        resolved_activity_unit=candidate.resolved_activity_unit,
        activity_dimension=candidate.activity_dimension,
        resolved_quantity_kg=candidate.resolved_quantity_kg,
        total_emissions_kgco2e=candidate.total_emissions_kgco2e,
    )
