"""Deterministic A1/A3 role assignment for process consumables."""

from __future__ import annotations

from .models import (
    AccountingAssignment,
    AccountingModule,
    AccountingQuantificationStatus,
    AccountingRole,
    ParameterEvidence,
)

ACCOUNTING_METADATA_FIELDS = (
    "accounting_role",
    "accounting_module",
    "process_emission_kind",
    "emission_names",
    "remark",
    "stoichiometric_formula",
    "formulas",
)


def _accounting_signal(item: ParameterEvidence) -> str:
    return " ".join((
        item.name,
        *(str(item.metadata.get(field, "")) for field in ACCOUNTING_METADATA_FIELDS),
    )).casefold()


def resolve_accounting_assignment(
    subject: str,
    *,
    use_context: str | None = None,
    evidence: tuple[ParameterEvidence, ...] = (),
    quantified: bool = False,
) -> AccountingAssignment:
    """Classify accounting modules from explicit use context and evidence metadata.

    Names help select a role, but a direct A3 assignment requires process-use
    evidence; a standalone material-factor lookup remains an A1 upstream input.
    """

    subject_text = subject.casefold()
    context_text = (use_context or "").casefold()
    direct_context = any(token in context_text for token in (
        "oxidation", "combustion", "direct process", "制造现场", "氧化", "燃烧", "过程排放",
    ))
    if any(token in subject_text for token in ("electrode", "电极")):
        role = AccountingRole.CONSUMABLE_ELECTRODE
    elif any(token in subject_text for token in ("reductant", "还原剂", "coke", "焦炭")):
        role = AccountingRole.REDUCTANT
    elif any(token in subject_text for token in ("process fuel", "工艺燃料")):
        role = AccountingRole.PROCESS_FUEL
    elif any(token in subject_text for token in ("retained", "保留组分", "组成")):
        role = AccountingRole.RETAINED_CONSTITUENT
    elif subject.strip():
        role = AccountingRole.PURCHASED_RAW_MATERIAL
    else:
        role = AccountingRole.UNKNOWN

    modules = (AccountingModule.A3_DIRECT_PROCESS,) if direct_context else (
        AccountingModule.A1_UPSTREAM_INPUT,
    )
    if direct_context:
        role = AccountingRole.DIRECT_PROCESS_EMISSION
        rationale = "evidenced on-site oxidation, combustion or reaction belongs to A3"
    else:
        rationale = "standalone purchased-material production factor belongs to A1 upstream"
    return AccountingAssignment(
        subject=subject,
        role=role,
        modules=modules,
        rationale=rationale,
        evidence_ids=tuple(item.parameter_id for item in evidence),
        quantification_status=(
            AccountingQuantificationStatus.QUANTIFIED
            if quantified
            else AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
        ),
        missing_inputs=() if quantified else ("emission_factor",),
    )


def resolve_process_accounting_assignments(
    target_product: str,
    evidence: tuple[ParameterEvidence, ...],
) -> tuple[AccountingAssignment, ...]:
    """Keep the product, purchased consumable and direct-emission event distinct."""

    target = AccountingAssignment(
        subject=target_product,
        role=AccountingRole.TARGET_PRODUCT,
        modules=(),
        rationale="target product is the accounting object, not a process consumable",
        quantification_status=AccountingQuantificationStatus.NOT_APPLICABLE,
    )
    target_evidence = tuple(
        item for item in evidence if item.name.startswith("target_")
    )
    evidence_text = " ".join(_accounting_signal(item) for item in target_evidence)
    consumable_evidence = tuple(
        item for item in target_evidence
        if any(token in _accounting_signal(item) for token in (
            "carbonaceous_consumable", "electrode", "电极", "coke", "焦炭",
            "reductant", "还原剂",
        ))
    )
    process_evidence = tuple(
        item for item in target_evidence
        if any(token in _accounting_signal(item)
               for token in ("process_emission", "oxidation", "combustion", "decomposition",
                             "过程排放", "氧化", "燃烧", "分解", "44/12"))
    )
    target_stoichiometric_names = {
        "target_carbonaceous_consumable_kg_per_t",
        "target_carbon_mass_fraction",
        "target_oxidation_fraction",
    }
    target_stoichiometric_evidence = tuple(
        item for item in target_evidence if item.name in target_stoichiometric_names
    )
    process_evidence = tuple({
        item.parameter_id: item
        for item in (*process_evidence, *target_stoichiometric_evidence)
    }.values())
    consumable_quantity_evidence = tuple(
        item for item in consumable_evidence
        if item.name in {
            "target_carbonaceous_consumable_kg_per_t",
            "target_electrode_kg_per_t",
            "target_coke_kg_per_t",
        }
    )
    consumable_factor_evidence = tuple(
        item for item in consumable_evidence
        if item.name in {
            "target_consumable_upstream_factor_kgco2e_per_kg",
            "target_electrode_upstream_factor_kgco2e_per_kg",
            "target_coke_upstream_factor_kgco2e_per_kg",
        }
    )
    process_is_quantified = any(
        item.name == "target_additional_process_emission_kgco2e_per_kg"
        for item in process_evidence
    ) or target_stoichiometric_names <= {item.name for item in target_evidence}
    if any(token in evidence_text for token in ("graphite electrode", "石墨电极")):
        consumable_subject = "石墨电极"
        consumable_role = AccountingRole.CONSUMABLE_ELECTRODE
    elif any(token in evidence_text for token in ("electrode", "电极")):
        consumable_subject = "电极"
        consumable_role = AccountingRole.CONSUMABLE_ELECTRODE
    elif any(token in evidence_text for token in ("coke", "焦炭", "reductant", "还原剂")):
        consumable_subject = "焦炭/还原剂"
        consumable_role = AccountingRole.REDUCTANT
    else:
        consumable_subject = ""
        consumable_role = AccountingRole.UNKNOWN

    assignments = [target]
    if consumable_subject:
        missing_inputs = tuple(
            name
            for name, present in (
                ("consumable_quantity_kg_per_t", bool(consumable_quantity_evidence)),
                ("consumable_upstream_factor_kgco2e_per_kg", bool(consumable_factor_evidence)),
            )
            if not present
        )
        assignments.append(AccountingAssignment(
            subject=consumable_subject,
            role=consumable_role,
            modules=(AccountingModule.A1_UPSTREAM_INPUT,),
            rationale=(
                "purchased consumable is identified as a separate A1 upstream input; "
                "identification evidence does not quantify its upstream production impact"
            ),
            evidence_ids=tuple(item.parameter_id for item in consumable_evidence),
            quantification_status=(
                AccountingQuantificationStatus.QUANTIFIED
                if not missing_inputs
                else AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
            ),
            missing_inputs=missing_inputs,
        ))
    if process_evidence:
        event_subject = (
            f"{consumable_subject}现场氧化/反应"
            if consumable_subject else f"{target_product}直接过程排放"
        )
        assignments.append(AccountingAssignment(
            subject=event_subject,
            role=AccountingRole.DIRECT_PROCESS_EMISSION,
            modules=(AccountingModule.A3_DIRECT_PROCESS,),
            rationale="on-site oxidation, combustion or decomposition is an A3 direct emission",
            evidence_ids=tuple(item.parameter_id for item in process_evidence),
            quantification_status=(
                AccountingQuantificationStatus.QUANTIFIED
                if process_is_quantified
                else AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
            ),
            missing_inputs=(
                () if process_is_quantified else ("direct_process_emission_calculation",)
            ),
        ))
    return tuple(assignments)
