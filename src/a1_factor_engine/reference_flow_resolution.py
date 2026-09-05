"""Deterministic unit and reference-flow transformations."""

from __future__ import annotations

from .derived_factor import derive_candidate
from .matching import normalize_text
from .models import (
    Candidate,
    NormalizedActivity,
    ReferenceFlowRecord,
    ResolutionType,
    RouterType,
    TransformationStep,
)
from .units import (
    convert_activity_decimal,
    convert_factor,
    parse_activity_unit,
    parse_factor_unit,
)


def _record_is_compatible(
    activity: NormalizedActivity,
    candidate: Candidate,
    record: ReferenceFlowRecord,
) -> bool:
    """Fail closed before a mass-per-package parameter enters arithmetic."""

    try:
        record_unit = parse_activity_unit(record.reference_unit)
        activity_unit = parse_activity_unit(activity.original_quantity_unit)
        if record_unit.canonical_unit != activity_unit.canonical_unit:
            return False
        if record_unit.dimension.value == "COUNT" and (
            record.reference_unit.strip().casefold()
            != activity.original_quantity_unit.strip().casefold()
        ):
            return False
    except ValueError:
        return False
    def norm(value: str | None) -> str:
        return normalize_text(value).value
    allowed_names = {
        norm(activity.canonical_name),
        *(norm(alias) for alias in activity.aliases),
        norm(candidate.source.material_name),
        norm(candidate.source.declared_product),
    }
    if norm(record.material_name) not in {item for item in allowed_names if item}:
        return False
    if record.declared_product and norm(record.declared_product) != norm(
        candidate.source.declared_product or candidate.source.material_name
    ):
        return False
    if record.product_form and norm(record.product_form) != norm(activity.product_form):
        return False
    if record.specification and norm(record.specification) != norm(activity.composition):
        return False
    if str(record.metadata.get("conflict_status", "")).casefold() in {
        "conflict", "rejected", "unresolved"
    }:
        return False
    return True


def resolve_reference_flow(
    activity: NormalizedActivity,
    candidate: Candidate,
    records: tuple[ReferenceFlowRecord, ...],
) -> tuple[Candidate, ...]:
    resolved: list[Candidate] = []
    for record in records:
        if not _record_is_compatible(activity, candidate, record):
            continue
        mass_kg = activity.original_quantity * record.mass_per_unit_kg
        factor_denominator = parse_factor_unit(
            candidate.factor_unit
        ).activity_unit.canonical_unit
        aligned_mass = float(convert_activity_decimal(
            mass_kg,
            "kg",
            factor_denominator,
        ))
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
            resolved_activity_value=aligned_mass,
            resolved_activity_unit=factor_denominator,
            activity_dimension="MASS",
            resolved_quantity_kg=mass_kg,
            total_emissions_kgco2e=emissions,
        ))
    return tuple(resolved)
