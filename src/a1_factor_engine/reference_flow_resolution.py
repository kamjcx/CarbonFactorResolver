"""Deterministic unit and reference-flow transformations."""

from __future__ import annotations

from .derived_factor import derive_candidate
from .models import (
    Candidate,
    NormalizedActivity,
    ReferenceFlowRecord,
    ResolutionType,
    RouterType,
    TransformationStep,
)
from .units import convert_factor


def resolve_reference_flow(
    activity: NormalizedActivity,
    candidate: Candidate,
    records: tuple[ReferenceFlowRecord, ...],
) -> tuple[Candidate, ...]:
    resolved: list[Candidate] = []
    for record in records:
        mass_kg = activity.original_quantity * record.mass_per_unit_kg
        factor_kg = convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        emissions = mass_kg * factor_kg
        step = TransformationStep(
            step_id=f"reference-flow:{candidate.candidate_id}:{record.record_id}",
            router_type=RouterType.REFERENCE_FLOW,
            method=record.method,
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=(record.evidence.parameter_id,),
            formula_id="reference_flow.mass_per_piece/v1",
            formula_expression="mass_kg = count * mass_per_unit_kg",
            input_values={
                "count": activity.original_quantity,
                "mass_per_unit_kg": record.mass_per_unit_kg,
            },
            output_value=mass_kg,
            output_unit="kg",
        )
        resolved.append(derive_candidate(
            candidate,
            candidate_id=f"{candidate.candidate_id}:reference-flow:{record.record_id}",
            resolution_type=ResolutionType.REFERENCE_FLOW_CONVERTED,
            steps=(step,),
            parameter_ids=(record.evidence.parameter_id,),
            reasons=(f"converted {activity.original_quantity:g} {activity.original_quantity_unit} using {record.mass_per_unit_kg:g} kg/unit",),
            limitations=((record.evidence.quality_note,) if record.evidence.quality_note else ()),
            resolved_quantity_kg=mass_kg,
            total_emissions_kgco2e=emissions,
        ))
    return tuple(resolved)
