"""Evidence-backed process-variant adjustment calculators."""

from __future__ import annotations

from dataclasses import replace

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
    "target_natural_gas_share": "fraction",
    "electricity_kgce_per_kwh": "kgce/kwh",
    "natural_gas_kgce_per_nm3": "kgce/nm3",
    "electricity_ef_kgco2e_per_kwh": "kgco2e/kwh",
    "natural_gas_ef_kgco2e_per_nm3": "kgco2e/nm3",
    "reference_additional_process_emission_kgco2e_per_kg": "kgco2e/kg",
    "target_additional_process_emission_kgco2e_per_kg": "kgco2e/kg",
}


def _by_name(evidence: tuple[ParameterEvidence, ...]) -> dict[str, ParameterEvidence]:
    result: dict[str, ParameterEvidence] = {}
    for item in evidence:
        if item.name in result:
            raise ValueError(f"ambiguous duplicate process parameter: {item.name}")
        result[item.name] = item
    return result


def _mark_process_dimension_resolved(candidate: Candidate) -> Candidate:
    """Re-score only the process dimension proven by a successful deterministic transformation."""

    dimensions = dict(candidate.dimensions)
    previous = dimensions.get("process", 0.0)
    dimensions["process"] = 1.0
    process_weight = 0.25 if candidate.origin.value == "proxy" else 0.20
    score = round(min(1.0, candidate.score + process_weight * (1.0 - previous)), 6)
    return replace(candidate, dimensions=dimensions, score=score)


def _reference_includes_process(
    candidate: Candidate, evidence: tuple[ParameterEvidence, ...]
) -> bool:
    declared = candidate.source.metadata.get("includes_process")
    if declared is not None and declared.casefold() in {"true", "1", "yes"}:
        return True
    return any(
        str(item.metadata.get("reference_includes_process", "")).casefold()
        in {"true", "1", "yes"}
        for item in evidence
    )


def _policy_assumptions(
    evidence: tuple[ParameterEvidence, ...],
) -> tuple[str, ...]:
    assumptions: list[str] = []
    if any(
        str(item.metadata.get("runtime_eligible", "")).casefold() == "false"
        for item in evidence
        if item.metadata.get("enterprise_energy_profile_id")
    ):
        assumptions.append(
            "exact enterprise energy profiles marked for review are used under the "
            "database-priority energy-replacement policy"
        )
    if any(
        item.metadata.get("parameter_scope")
        == "unique_generic_energy_carrier_fallback"
        for item in evidence
    ):
        assumptions.append(
            "unique database energy-carrier parameters are reused across material routes"
        )
    if any(
        item.metadata.get("process_inclusion_basis") == "policy_assumption"
        for item in evidence
    ):
        assumptions.append(
            "the lifecycle reference is assumed to include route energy under the "
            "database-priority policy"
        )
    return tuple(assumptions)


def resolve_process_variant(
    candidate: Candidate,
    evidence: tuple[ParameterEvidence, ...],
) -> tuple[Candidate, ProcessResolutionMode]:
    parameters = _by_name(evidence)
    if FULL_REQUIRED <= parameters.keys():
        for name, expected in EXPECTED_UNITS.items():
            if name not in parameters:
                continue
            observed = parameters[name].unit.casefold().replace(" ", "")
            if observed != expected:
                raise ValueError(f"{name} unit must be {expected}")
        values = {name: parameters[name].value for name in FULL_REQUIRED}
        target_gas_share = parameters.get("target_natural_gas_share")
        values["target_natural_gas_share"] = target_gas_share.value if target_gas_share else 0.0
        reference_additional = parameters.get(
            "reference_additional_process_emission_kgco2e_per_kg"
        )
        target_additional = parameters.get(
            "target_additional_process_emission_kgco2e_per_kg"
        )
        values["reference_additional_process"] = (
            reference_additional.value if reference_additional else 0.0
        )
        values["target_additional_process"] = (
            target_additional.value if target_additional else 0.0
        )
        for share in (
            "reference_electricity_share",
            "reference_natural_gas_share",
            "target_electricity_share",
            "target_natural_gas_share",
        ):
            if not 0 <= values[share] <= 1:
                raise ValueError(f"{share} must be between zero and one")
        for name, value in values.items():
            if (
                value <= 0
                and "share" not in name
                and "additional_process" not in name
            ):
                raise ValueError(f"{name} must be positive")
        if abs(values["reference_electricity_share"] + values["reference_natural_gas_share"] - 1.0) > 1e-6:
            raise ValueError("reference process energy shares must sum to one")
        if abs(values["target_electricity_share"] + values["target_natural_gas_share"] - 1.0) > 1e-6:
            raise ValueError("target process energy shares must sum to one; target energy cannot silently disappear")
        if not _reference_includes_process(candidate, evidence):
            raise ValueError(
                "reference factor or scoped evidence must explicitly confirm that it includes the removed process"
            )

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
        target_gas = (
            values["target_total_energy_kgce_per_t"]
            * values["target_natural_gas_share"]
            / values["natural_gas_kgce_per_nm3"]
            * values["natural_gas_ef_kgco2e_per_nm3"]
            / 1000
        )
        if (
            values["reference_additional_process"] < 0
            or values["target_additional_process"] < 0
        ):
            raise ValueError("additional process emissions must be non-negative")
        reference_process = (
            ref_electricity + ref_gas + values["reference_additional_process"]
        )
        base_factor = convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        common_upstream = base_factor - reference_process
        if common_upstream < -1e-12:
            raise ValueError("process decomposition produced a negative common upstream factor")
        common_upstream = max(0.0, common_upstream)
        output_kg = (
            common_upstream
            + target_electricity
            + target_gas
            + values["target_additional_process"]
        )
        output = convert_factor(output_kg, "kgCO2e/kg", candidate.factor_unit)
        inclusion_evidence = next((
            item for item in evidence
            if str(item.metadata.get("reference_includes_process", "")).casefold()
            in {"true", "1", "yes"}
        ), None)
        used_parameter_ids = tuple(
            parameters[name].parameter_id
            for name in sorted(
                FULL_REQUIRED
                | ({"target_natural_gas_share"} if target_gas_share else set())
                | ({reference_additional.name} if reference_additional else set())
                | ({target_additional.name} if target_additional else set())
            )
        ) + ((inclusion_evidence.parameter_id,) if inclusion_evidence else ())
        assumptions = (
            "common raw-material upstream is equivalent between reference and target routes",
            "raw-material losses and product yield are equivalent",
            "the reference factor includes the removed process energy",
            "target and reference process-energy boundaries are compatible",
            "m3 and Nm3 are treated as the same quantity basis for this proxy",
            *_policy_assumptions(evidence),
        )
        includes_additional_process = bool(reference_additional or target_additional)
        formula_id = (
            "process.replace_energy_and_additional_process/v2"
            if includes_additional_process
            else "process.replace_energy_components/v1"
        )
        formula_expression = (
            "EF_target = EF_reference - EF_reference_energy "
            "- EF_reference_additional_process + EF_target_energy "
            "+ EF_target_additional_process"
            if includes_additional_process
            else "EF_target = EF_reference - EF_reference_process + EF_target_process"
        )
        step = TransformationStep(
            step_id=f"process:{candidate.candidate_id}:replace-energy",
            router_type=RouterType.PROCESS_VARIANT,
            method=ProcessResolutionMode.DECOMPOSE_AND_REBUILD.value,
            input_source_ids=(candidate.source.source_id,),
            parameter_ids=used_parameter_ids,
            formula_id=formula_id,
            formula_expression=formula_expression,
            input_values={
                "ef_reference": base_factor,
                "reference_electricity": ref_electricity,
                "reference_natural_gas": ref_gas,
                "reference_additional_process": values["reference_additional_process"],
                "common_upstream": common_upstream,
                "target_electricity": target_electricity,
                "target_natural_gas": target_gas,
                "target_additional_process": values["target_additional_process"],
            },
            output_value=output,
            output_unit=candidate.factor_unit,
            assumptions=assumptions,
        )
        return _mark_process_dimension_resolved(derive_candidate(
            candidate,
            candidate_id=f"{candidate.candidate_id}:process-adjusted",
            resolution_type=ResolutionType.PROCESS_ADJUSTED,
            factor_value=output,
            steps=(step,),
            parameter_ids=step.parameter_ids,
            reasons=("replaced evidence-backed reference process energy with target process energy",),
            assumptions=assumptions,
        )), ProcessResolutionMode.DECOMPOSE_AND_REBUILD

    delta_required = {"removed_process_factor", "added_process_factor"}
    if delta_required <= parameters.keys():
        for name in delta_required | ({"delta_other"} if "delta_other" in parameters else set()):
            unit = parameters[name].unit.casefold().replace(" ", "")
            if unit not in {"kgco2e/kg", "tco2e/t"}:
                raise ValueError(f"{name} unit must be kgCO2e/kg or tCO2e/t")
        if not _reference_includes_process(candidate, evidence):
            raise ValueError("cannot subtract a process without explicit evidence that the reference factor includes it")
        removed = parameters["removed_process_factor"].value
        added = parameters["added_process_factor"].value
        delta_other = parameters.get("delta_other")
        delta = delta_other.value if delta_other else 0.0
        base_factor = convert_factor(candidate.factor_value, candidate.factor_unit, "kgCO2e/kg")
        common_upstream = base_factor - removed
        output_kg = common_upstream + added + delta
        if removed < 0 or added < 0 or common_upstream < -1e-12 or output_kg < 0:
            raise ValueError("delta process adjustment requires non-negative components and output")
        common_upstream = max(0.0, common_upstream)
        output_kg = common_upstream + added + delta
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
            input_values={
                "ef_reference": base_factor,
                "removed": removed,
                "common_upstream": common_upstream,
                "added": added,
                "delta_other": delta,
            },
            output_value=output,
            output_unit=candidate.factor_unit,
            assumptions=("unadjusted contributions are shared between process variants",),
        )
        return _mark_process_dimension_resolved(derive_candidate(
            candidate,
            candidate_id=f"{candidate.candidate_id}:process-delta",
            resolution_type=ResolutionType.PROCESS_ADJUSTED,
            factor_value=output,
            steps=(step,),
            parameter_ids=used,
            reasons=("applied an evidence-backed process delta adjustment",),
            assumptions=step.assumptions,
        )), ProcessResolutionMode.DELTA_ADJUST

    return derive_candidate(
        candidate,
        candidate_id=f"{candidate.candidate_id}:unadjusted-process-proxy",
        resolution_type=ResolutionType.UNADJUSTED_PROCESS_PROXY,
        reasons=("same or related material with a different production route",),
        limitations=("no supported process decomposition; source factor is unchanged",),
        assumptions=("reference process is used as an unadjusted proxy",),
    ), ProcessResolutionMode.UNADJUSTED_PROCESS_PROXY
