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
from .units import convert_factor, is_mass_unit


def resolve_unit_scale(activity: NormalizedActivity, candidate: Candidate) -> Candidate:
    steps: list[TransformationStep] = []
    if is_mass_unit(activity.original_quantity_unit) and activity.original_quantity_unit.strip().lower() != "kg":
        assert activity.quantity_kg is not None
        steps.append(TransformationStep(
            step_id=f"unit:{candidate.candidate_id}:activity-mass",
            router_type=RouterType.UNIT_SCALE,
            method="MASS_SCALE_CONVERSION",
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=(),
            formula_id="unit.mass_scale/v1",
            formula_expression="quantity_kg = quantity * mass_unit_to_kg",
            input_values={"quantity": activity.original_quantity},
            output_value=activity.quantity_kg,
            output_unit="kg",
        ))
    source_unit = candidate.source.factor_unit.casefold().replace(" ", "")
    target_unit = candidate.factor_unit.casefold().replace(" ", "")
    if source_unit != target_unit:
        steps.append(TransformationStep(
            step_id=f"unit:{candidate.candidate_id}:factor",
            router_type=RouterType.UNIT_SCALE,
            method="FACTOR_SCALE_CONVERSION",
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=(),
            formula_id="unit.factor_scale/v1",
            formula_expression="factor_target = convert_mass_ratio(factor_source)",
            input_values={"source_factor": candidate.source.factor_value},
            output_value=convert_factor(candidate.source.factor_value, candidate.source.factor_unit, candidate.factor_unit),
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
    )
