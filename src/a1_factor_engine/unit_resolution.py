"""Versioned deterministic unit-scale transformations."""

from __future__ import annotations

from .derived_factor import derive_candidate
from .models import (
    Candidate,
    NormalizedActivity,
    ResolutionType,
    RouterType,
    TransformationStep,
)
from .units import (
    convert_activity_decimal,
    convert_factor_decimal,
    parse_activity_unit,
    parse_factor_unit,
)


def resolve_unit_scale(activity: NormalizedActivity, candidate: Candidate) -> Candidate:
    steps: list[TransformationStep] = []
    target_activity_unit = parse_factor_unit(candidate.factor_unit).activity_unit.canonical_unit
    original_activity_spec = parse_activity_unit(activity.original_quantity_unit)
    target_activity_spec = parse_activity_unit(target_activity_unit)
    if original_activity_spec.dimension != target_activity_spec.dimension:
        # A reference-flow router may resolve this with controlled mass-per-unit
        # evidence. Unit scale alone must never infer a cross-dimension ratio.
        return candidate
    if activity.original_quantity_unit.strip().casefold() != target_activity_unit.casefold():
        converted_quantity = float(convert_activity_decimal(
            activity.original_quantity,
            activity.original_quantity_unit,
            target_activity_unit,
            evidence=activity.unit_conversion_evidence,
        ))
        steps.append(TransformationStep(
            step_id=f"unit:{candidate.candidate_id}:activity",
            router_type=RouterType.UNIT_SCALE,
            method="ACTIVITY_SCALE_CONVERSION",
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=(
                (activity.unit_conversion_evidence.evidence_id,)
                if activity.unit_conversion_evidence else ()
            ),
            formula_id="unit.activity_scale/v1",
            formula_expression="quantity_target = quantity * activity_unit_multiplier",
            input_values={"quantity": activity.original_quantity},
            output_value=converted_quantity,
            output_unit=target_activity_unit,
        ))
    source_unit = candidate.source.factor_unit.casefold().replace(" ", "")
    target_unit = candidate.factor_unit.casefold().replace(" ", "")
    if source_unit != target_unit:
        steps.append(TransformationStep(
            step_id=f"unit:{candidate.candidate_id}:factor",
            router_type=RouterType.UNIT_SCALE,
            method="FACTOR_SCALE_CONVERSION",
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=(
                (activity.unit_conversion_evidence.evidence_id,)
                if activity.unit_conversion_evidence else ()
            ),
            formula_id="unit.factor_scale/v1",
            formula_expression="factor_target = convert_mass_ratio(factor_source)",
            input_values={"source_factor": candidate.source.factor_value},
            output_value=float(convert_factor_decimal(
                candidate.source.factor_value,
                candidate.source.factor_unit,
                candidate.factor_unit,
                evidence=activity.unit_conversion_evidence,
            )),
            output_unit=candidate.factor_unit,
        ))
    if not steps:
        return candidate
    resolution_type = (
        ResolutionType.UNIT_CONVERTED
        if candidate.resolution_type in {
            ResolutionType.DIRECT_EXACT,
            ResolutionType.DIRECT_ALIAS,
            ResolutionType.UNIT_CONVERTED,
        }
        else candidate.resolution_type
    )
    return derive_candidate(
        candidate,
        candidate_id=f"{candidate.candidate_id}:unit-converted",
        resolution_type=resolution_type,
        steps=tuple(steps),
        reasons=("applied deterministic unit-scale conversion",),
        total_emissions_kgco2e=candidate.total_emissions_kgco2e,
    )
