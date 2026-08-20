"""Evidence-backed process-variant adjustment calculators."""

from __future__ import annotations

from .derived_factor import derive_candidate
from .models import (
    Candidate,
    ParameterEvidence,
    ProcessResolutionMode,
    ResolutionType,
    RouterType,
    TransformationStep,
)
from .units import convert_factor

FULL_REQUIRED = frozenset({
    "reference_total_energy_kgce_per_t",
    "reference_electricity_share",
    "reference_natural_gas_share",
    "target_total_energy_kgce_per_t",
    "target_electricity_share",
    "electricity_kgce_per_kwh",
    "natural_gas_kgce_per_nm3",
    "electricity_ef_kgco2e_per_kwh",
    "natural_gas_ef_kgco2e_per_nm3",
})

EXPECTED_UNITS = {
    "reference_total_energy_kgce_per_t": "kgce/t",
    "reference_electricity_share": "fraction",
    "reference_natural_gas_share": "fraction",
    "target_total_energy_kgce_per_t": "kgce/t",
    "target_electricity_share": "fraction",
    "electricity_kgce_per_kwh": "kgce/kwh",
    "natural_gas_kgce_per_nm3": "kgce/nm3",
    "electricity_ef_kgco2e_per_kwh": "kgco2e/kwh",
    "natural_gas_ef_kgco2e_per_nm3": "kgco2e/nm3",
}


def _by_name(evidence: tuple[ParameterEvidence, ...]) -> dict[str, ParameterEvidence]:
    result: dict[str, ParameterEvidence] = {}
    for item in evidence:
        if item.name in result:
            raise ValueError(f"ambiguous duplicate process parameter: {item.name}")
        result[item.name] = item
    return result


def resolve_process_variant(
    candidate: Candidate,
    evidence: tuple[ParameterEvidence, ...],
) -> tuple[Candidate, ProcessResolutionMode]:
    parameters = _by_name(evidence)
    if FULL_REQUIRED <= parameters.keys():
        for name, expected in EXPECTED_UNITS.items():
            observed = parameters[name].unit.casefold().replace(" ", "")
            if observed != expected:
                raise ValueError(f"{name} unit must be {expected}")
        values = {name: parameters[name].value for name in FULL_REQUIRED}
        for share in ("reference_electricity_share", "reference_natural_gas_share", "target_electricity_share"):
            if not 0 <= values[share] <= 1:
                raise ValueError(f"{share} must be between zero and one")
        for name, value in values.items():
            if value <= 0 and "share" not in name:
                raise ValueError(f"{name} must be positive")
        if abs(values["reference_electricity_share"] + values["reference_natural_gas_share"] - 1.0) > 1e-6:
            raise ValueError("reference process energy shares must sum to one")

        ref_electricity = (
            values["reference_total_energy_kgce_per_t"]
            * values["reference_electricity_share"]
            / values["electricity_kgce_per_kwh"]
            * values["electricity_ef_kgco2e_per_kwh"]
            / 1000
        )
        ref_gas = (
            values["reference_total_energy_kgce_per_t"]
            * values["reference_natural_gas_share"]
            / values["natural_gas_kgce_per_nm3"]
            * values["natural_gas_ef_kgco2e_per_nm3"]
            / 1000
        )
        target_electricity = (
            values["target_total_energy_kgce_per_t"]
            * values["target_electricity_share"]
            / values["electricity_kgce_per_kwh"]
            * values["electricity_ef_kgco2e_per_kwh"]
            / 1000
        )
        reference_process = ref_electricity + ref_gas
        base_factor = convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        output_kg = base_factor - reference_process + target_electricity
        if output_kg < 0:
            raise ValueError("process decomposition produced a negative common upstream factor")
        output = convert_factor(output_kg, "kgCO2e/kg", candidate.factor_unit)
        assumptions = (
            "common raw-material upstream is equivalent between reference and target routes",
            "raw-material losses and product yield are equivalent",
            "the reference factor includes the removed process energy",
            "target and reference process-energy boundaries are compatible",
            "m3 and Nm3 are treated as the same quantity basis for this proxy",
        )
        step = TransformationStep(
            step_id=f"process:{candidate.candidate_id}:replace-energy",
            router_type=RouterType.PROCESS_VARIANT,
            method=ProcessResolutionMode.DECOMPOSE_AND_REBUILD.value,
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=tuple(parameters[name].parameter_id for name in sorted(FULL_REQUIRED)),
            formula_id="process.replace_energy_components/v1",
            formula_expression="EF_target = EF_reference - EF_reference_process + EF_target_process",
            input_values={
                "ef_reference": base_factor,
                "reference_electricity": ref_electricity,
                "reference_natural_gas": ref_gas,
                "target_electricity": target_electricity,
            },
            output_value=output,
            output_unit=candidate.factor_unit,
            assumptions=assumptions,
        )
        return derive_candidate(
            candidate,
            candidate_id=f"{candidate.candidate_id}:process-adjusted",
            resolution_type=ResolutionType.PROCESS_ADJUSTED,
            factor_value=output,
            steps=(step,),
            parameter_ids=step.parameter_ids,
            reasons=("replaced evidence-backed reference process energy with target process energy",),
            assumptions=assumptions,
        ), ProcessResolutionMode.DECOMPOSE_AND_REBUILD

    delta_required = {"removed_process_factor", "added_process_factor"}
    if delta_required <= parameters.keys():
        for name in delta_required | ({"delta_other"} if "delta_other" in parameters else set()):
            unit = parameters[name].unit.casefold().replace(" ", "")
            if unit not in {"kgco2e/kg", "tco2e/t"}:
                raise ValueError(f"{name} unit must be kgCO2e/kg or tCO2e/t")
        if candidate.source.metadata.get("includes_process", "true").casefold() in {"false", "0", "no"}:
            raise ValueError("cannot subtract a process that the reference factor does not include")
        removed = parameters["removed_process_factor"].value
        added = parameters["added_process_factor"].value
        delta_other = parameters.get("delta_other")
        delta = delta_other.value if delta_other else 0.0
        base_factor = convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        output_kg = base_factor - removed + added + delta
        if removed < 0 or added < 0 or output_kg < 0:
            raise ValueError("delta process adjustment requires non-negative components and output")
        output = convert_factor(output_kg, "kgCO2e/kg", candidate.factor_unit)
        used = tuple(parameters[name].parameter_id for name in sorted(delta_required | ({"delta_other"} if delta_other else set())))
        step = TransformationStep(
            step_id=f"process:{candidate.candidate_id}:delta",
            router_type=RouterType.PROCESS_VARIANT,
            method=ProcessResolutionMode.DELTA_ADJUST.value,
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=used,
            formula_id="process.delta_adjust/v1",
            formula_expression="EF_target = EF_reference - EF_removed + EF_added + delta_other",
            input_values={"ef_reference": base_factor, "removed": removed, "added": added, "delta_other": delta},
            output_value=output,
            output_unit=candidate.factor_unit,
            assumptions=("unadjusted contributions are shared between process variants",),
        )
        return derive_candidate(
            candidate,
            candidate_id=f"{candidate.candidate_id}:process-delta",
            resolution_type=ResolutionType.PROCESS_ADJUSTED,
            factor_value=output,
            steps=(step,),
            parameter_ids=used,
            reasons=("applied an evidence-backed process delta adjustment",),
            assumptions=step.assumptions,
        ), ProcessResolutionMode.DELTA_ADJUST

    return derive_candidate(
        candidate,
        candidate_id=f"{candidate.candidate_id}:unadjusted-process-proxy",
        resolution_type=ResolutionType.UNADJUSTED_PROCESS_PROXY,
        reasons=("same or related material with a different production route",),
        limitations=("no supported process decomposition; source factor is unchanged",),
        assumptions=("reference process is used as an unadjusted proxy",),
    ), ProcessResolutionMode.UNADJUSTED_PROCESS_PROXY
