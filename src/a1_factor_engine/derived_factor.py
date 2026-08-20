"""Helpers for provenance-preserving derived factor candidates."""

from __future__ import annotations

from dataclasses import replace

from .models import (
    Candidate,
    DerivedFactorCandidate,
    FactorSourceType,
    ResolutionType,
    ResultTier,
    TransformationStep,
)

TYPE_PRIORITY = {
    ResolutionType.DIRECT_EXACT: 0,
    ResolutionType.DIRECT_ALIAS: 1,
    ResolutionType.UNIT_CONVERTED: 2,
    ResolutionType.REFERENCE_FLOW_CONVERTED: 3,
    ResolutionType.PROCESS_ADJUSTED: 4,
    ResolutionType.GRADE_INTERPOLATED: 5,
    ResolutionType.GRADE_ADJUSTED: 5,
    ResolutionType.GRADE_PROXY: 6,
    ResolutionType.UNADJUSTED_PROCESS_PROXY: 7,
    ResolutionType.CLASS_TECHNICAL_PROXY: 8,
    ResolutionType.CLASS_GENERIC_PROXY: 9,
}

SOURCE_QUALITY = {
    FactorSourceType.SUPPLIER: 1.0,
    FactorSourceType.LOCAL_DATABASE: 0.9,
    FactorSourceType.EPD: 0.9,
    FactorSourceType.LITERATURE: 0.7,
    FactorSourceType.EXTERNAL_DATABASE: 0.75,
}


def resolution_strength(
    candidate: Candidate,
    *,
    step_count: int | None = None,
    assumption_count: int | None = None,
) -> float:
    steps = len(candidate.transformation_steps) if step_count is None else step_count
    assumptions = len(candidate.assumptions) if assumption_count is None else assumption_count
    source_quality = SOURCE_QUALITY.get(candidate.source.source_type, 0.6)
    derivation_signal = max(0.0, 1.0 - 0.12 * steps - 0.06 * assumptions)
    gap_penalty = min(0.25, 0.05 * sum(gap.severity for gap in candidate.gaps))
    return round(min(1.0, max(0.0,
        0.45 * candidate.score
        + 0.30 * candidate.evidence_coverage
        + 0.15 * source_quality
        + 0.10 * derivation_signal
        - gap_penalty
    )), 6)


def tier_for(candidate: Candidate) -> ResultTier:
    if candidate.resolution_type in {ResolutionType.DIRECT_EXACT, ResolutionType.DIRECT_ALIAS, ResolutionType.UNIT_CONVERTED}:
        if any(gap.severity >= 0.5 for gap in candidate.gaps):
            return ResultTier.USABLE_WITH_ASSUMPTIONS
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


def finalize_candidate(candidate: Candidate) -> Candidate:
    tier = tier_for(candidate)
    strength = resolution_strength(candidate)
    return replace(candidate, result_tier=tier, resolution_strength=strength)


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
    resolved_quantity_kg: float | None = None,
    total_emissions_kgco2e: float | None = None,
) -> Candidate:
    candidate = replace(
        base,
        candidate_id=candidate_id,
        factor_value=base.factor_value if factor_value is None else factor_value,
        resolution_type=resolution_type,
        transformation_steps=base.transformation_steps + steps,
        parameter_evidence_ids=tuple(dict.fromkeys(base.parameter_evidence_ids + parameter_ids)),
        base_source_ids=tuple(dict.fromkeys(base.base_source_ids + (base.source.source_id,) + base_source_ids)),
        reasons=base.reasons + reasons,
        limitations=tuple(dict.fromkeys(base.limitations + limitations)),
        assumptions=tuple(dict.fromkeys(base.assumptions + assumptions)),
        warnings=tuple(dict.fromkeys(base.warnings + warnings)),
        resolved_quantity_kg=resolved_quantity_kg if resolved_quantity_kg is not None else base.resolved_quantity_kg,
        total_emissions_kgco2e=(
            total_emissions_kgco2e if total_emissions_kgco2e is not None else base.total_emissions_kgco2e
        ),
    )
    return finalize_candidate(candidate)


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
        resolved_quantity_kg=candidate.resolved_quantity_kg,
        total_emissions_kgco2e=candidate.total_emissions_kgco2e,
    )
