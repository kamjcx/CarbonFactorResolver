"""Concrete graph nodes and deterministic candidate evaluation."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Sequence

from .accounting import (
    resolve_accounting_assignment,
    resolve_process_accounting_assignments,
)
from .derived_factor import TYPE_PRIORITY, finalize_candidate, to_derived
from .gap_analysis import analyze_candidate_gaps
from .grade_resolution import resolve_grade
from .graph import (
    GraphState,
    Node,
    Stage,
    candidate_hard_rejection_reasons,
    candidate_is_sufficient,
    candidate_rejection_reasons,
)
from .matching import calibrate_confidence, normalize_text
from .material_registry import (
    DEFAULT_MATERIAL_REGISTRY,
    MaterialRuleSuggestionPort,
    MaterialSemanticRegistryPort,
)
from .models import (
    AccountingAssignment,
    AccountingModule,
    AccountingQuantificationStatus,
    AccountingRole,
    Candidate,
    CandidateAdmission,
    CandidateExclusion,
    CandidateOrigin,
    CandidateQualification,
    FactorSubjectType,
    GapType,
    LinkAttempt,
    LinkOutcome,
    LinkStrategy,
    MaterialCategory,
    MaterialClass,
    NormalizedActivity,
    ParameterEvidence,
    ProvisionalOption,
    QualificationDiagnostic,
    QualificationPolicy,
    RecallObservation,
    RequestGap,
    RequestGapType,
    RequestResolutionPlan,
    ResolutionType,
    ResultTier,
    RouterType,
    SourceRecord,
    normalized_business_fingerprint,
)
from .ports import (
    FactorRepositoryPort,
    GradeSeriesRepositoryPort,
    MaterialUnderstandingPort,
    ProcessParameterRepositoryPort,
    ProxyRepositoryPort,
    ReferenceFlowRepositoryPort,
)
from .process_adjustment import resolve_process_variant
from .qualification import (
    EXPLICIT_NON_MATERIAL_SUBJECTS,
    OPERATIONAL_FACTOR_SUBJECTS,
    SOURCE_DOCUMENT_HASH_REQUIRED,
    qualify_record,
)
from .qualification import (
    material_identity as _material_identity,
)
from .qualification import (
    source_identity as _source_identity,
)
from .reference_flow_resolution import resolve_reference_flow
from .resolution_planner import build_resolution_plan
from .semantic_index import CatalogIntegrityError
from .unit_resolution import resolve_unit_scale
from .units import (
    CATALOG_FACTOR_UNIT_INVALID,
    UNIT_CONVERSION_EVIDENCE_REQUIRED,
    UNIT_DIMENSION_MISMATCH,
    UNIT_SYNTAX_UNSUPPORTED,
    ActivityDimension,
    UnitConversionError,
    convert_activity_decimal,
    parse_activity_unit,
    parse_factor_unit,
    plan_factor_conversion,
)


def _text(value: str | None) -> str:
    return normalize_text(value).value


def _parameter_database_anchors(evidence: Sequence[ParameterEvidence]) -> tuple[dict[str, str], ...]:
    anchors: dict[str, dict[str, str]] = {}
    for item in evidence:
        metadata = item.metadata
        digest = metadata.get("evidence_database_sha256")
        if not digest:
            continue
        anchors.setdefault(digest, {
            "database_name": metadata.get("evidence_database_name", "unknown"),
            "dataset_version": metadata.get("evidence_database_version", "unknown"),
            "database_sha256": digest,
            "locator": metadata.get("evidence_database_locator", "unknown"),
            "schema_version": metadata.get("evidence_database_schema_version", "unknown"),
        })
    return tuple(anchors[key] for key in sorted(anchors))


def _source_priority_rank(candidate: Candidate) -> int:
    try:
        return int(candidate.source.metadata.get("source_priority_rank", "100") or 100)
    except (TypeError, ValueError):
        return 100


def _applicability_rank(candidate: Candidate) -> tuple[int, float]:
    """Keep explicit geography/year compatibility ahead of source preference."""

    applicability_gaps = tuple(
        gap for gap in candidate.gaps
        if gap.gap_type in {GapType.GEOGRAPHY, GapType.TEMPORAL}
    )
    if not applicability_gaps:
        return (0, 0.0)
    maximum = max(gap.severity for gap in applicability_gaps)
    return (2 if maximum >= 0.5 else 1, maximum)


def _canonical_product_form(value: str | None) -> str | None:
    observed = _text(value)
    return {
        "纤维": "fiber",
        "fibre": "fiber",
        "钢纤维": "fiber",
    }.get(observed, observed or None)


def _reference_flow_required_fields(unit: str) -> tuple[str, ...]:
    observed = _text(unit)
    if observed in {"piece", "pieces", "count", "unit", "个", "件"}:
        return ("mass_per_piece", "dimensions+density")
    if observed in {"m3", "m³", "cubic metre", "cubic meter"}:
        return ("density",)
    if observed in {"m2", "m²", "square metre", "square meter"}:
        return ("thickness", "density")
    if observed in {"bag", "袋"}:
        return ("mass_per_bag",)
    if observed in {"roll", "卷"}:
        return ("mass_per_roll",)
    return (f"mass_per_{observed or 'reference_unit'}",)


def _tokens(value: str | None) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", _text(value)) if len(x) > 1}


def _dimension(query: str | None, observed: str | None) -> float:
    q, o = _text(query), _text(observed)
    if not q and not o:
        return 0.5
    if not q or not o:
        return 0.5
    if q == o:
        return 1.0
    qt, ot = _tokens(q), _tokens(o)
    if qt and ot and (qt <= ot or ot <= qt):
        return 0.8
    if qt and ot:
        overlap = len(qt & ot) / max(len(qt | ot), 1)
        if overlap >= 0.35:
            return 0.65
    return 0.0


def _material_dimension(activity: NormalizedActivity, source: SourceRecord, origin: CandidateOrigin, material_class: MaterialClass | None) -> float:
    if origin == CandidateOrigin.PROXY:
        if material_class is None:
            return 0.0
        haystack = " ".join(
            [_text(source.material_name), _text(source.metadata.get("material_class")), _text(source.metadata.get("family"))]
        )
        target = [_text(material_class.name), _text(material_class.family)]
        if any(x and x in haystack for x in target):
            return 1.0
        # A proxy may be explicitly provided by a process-compatible repository
        # without repeating the class in its title.
        return 0.5
    target_entity_id = (
        activity.material_identity.base_entity_id
        if activity.material_identity else None
    )
    source_entity_id = source.metadata.get("base_entity_id")
    if target_entity_id and source_entity_id and target_entity_id == source_entity_id:
        return 1.0
    names = {_text(activity.canonical_name)} | {_text(x) for x in activity.aliases}
    observed = _text(source.material_name)
    if observed in names:
        return 1.0
    if any(n and (n in observed or observed in n) for n in names):
        return 0.8
    return _dimension(activity.canonical_name, source.material_name)


WEIGHTS_DIRECT = {
    "material": 0.25,
    "process": 0.20,
    "form": 0.10,
    "composition": 0.15,
    "geography": 0.10,
    "time": 0.10,
    "boundary": 0.10,
}
WEIGHTS_PROXY = {
    "material": 0.10,
    "process": 0.25,
    "form": 0.15,
    "composition": 0.20,
    "geography": 0.10,
    "time": 0.10,
    "boundary": 0.10,
}


def _proxy_weights(material_class: MaterialClass | None) -> dict[str, float]:
    if material_class is None:
        return WEIGHTS_PROXY
    if material_class.category == MaterialCategory.NATURAL_MINERAL:
        return {"material": 0.15, "process": 0.25, "form": 0.15, "composition": 0.15, "geography": 0.10, "time": 0.10, "boundary": 0.10}
    if material_class.category == MaterialCategory.MANUFACTURED_MINERAL:
        return {"material": 0.10, "process": 0.30, "form": 0.10, "composition": 0.20, "geography": 0.10, "time": 0.10, "boundary": 0.10}
    if material_class.category == MaterialCategory.SYNTHETIC_CHEMICAL:
        return {"material": 0.20, "process": 0.25, "form": 0.05, "composition": 0.25, "geography": 0.10, "time": 0.05, "boundary": 0.10}
    return WEIGHTS_PROXY


def _evaluate_dimensions(activity: NormalizedActivity, source: SourceRecord, origin: CandidateOrigin, material_class: MaterialClass | None) -> dict[str, float]:
    dimensions = {
        "material": _material_dimension(activity, source, origin, material_class),
        "process": _dimension(activity.production_process, source.production_process),
        "form": _dimension(activity.product_form, source.product_form),
        "composition": _dimension(activity.composition, source.composition),
        "geography": _dimension(activity.geography, source.geography),
        "time": 1.0 if activity.year is None and source.year is None else 0.5,
        "boundary": _dimension(activity.boundary, source.boundary),
    }
    if activity.year is not None and source.year is not None:
        delta = abs(activity.year - source.year)
        dimensions["time"] = 1.0 if delta == 0 else 0.8 if delta <= 3 else 0.5 if delta <= 10 else 0.2
    return dimensions


def _evidence_coverage(
    activity: NormalizedActivity,
    source: SourceRecord,
    weights: dict[str, float],
) -> tuple[float, tuple[str, ...]]:
    pairs = {
        "material": (activity.canonical_name, source.material_name),
        "process": (activity.production_process, source.production_process),
        "form": (activity.product_form, source.product_form),
        "composition": (activity.composition, source.composition),
        "geography": (activity.geography, source.geography),
        "time": (activity.year, source.year),
        "boundary": (activity.boundary, source.boundary),
    }
    covered = 0.0
    gaps: list[str] = []
    for dimension, weight in weights.items():
        target, observed = pairs[dimension]
        if target not in (None, "") and observed not in (None, ""):
            covered += weight
            continue
        if target in (None, ""):
            gaps.append(f"missing_target_{dimension}")
        if observed in (None, ""):
            gaps.append(f"missing_source_{dimension}")
    return round(covered / sum(weights.values()), 6), tuple(gaps)


def _candidate(
    activity: NormalizedActivity,
    source: SourceRecord,
    origin: CandidateOrigin,
    semantic_note: str = "",
    semantic_limitations: tuple[str, ...] = (),
    material_class: MaterialClass | None = None,
) -> tuple[Candidate | None, str | None]:
    try:
        factor_plan = plan_factor_conversion(
            source.factor_unit,
            activity.target_factor_unit,
            evidence=activity.unit_conversion_evidence,
        )
        if (
            factor_plan.reason_code == UNIT_DIMENSION_MISMATCH
            and activity.target_factor_unit_derived
            and (
                activity.activity_dimension == "COUNT"
                or activity.activity_dimension == "VOLUME" and bool(activity.product_form)
            )
            and parse_factor_unit(source.factor_unit).activity_unit.dimension
            == ActivityDimension.MASS
        ):
            value = source.factor_value
            candidate_factor_unit = source.factor_unit
            resolved_quantity = None
        else:
            value = float(factor_plan.convert(source.factor_value))
            candidate_factor_unit = activity.target_factor_unit
            target_denominator = parse_factor_unit(activity.target_factor_unit).activity_unit.canonical_unit
            resolved_quantity = float(convert_activity_decimal(
                activity.original_quantity,
                activity.original_quantity_unit,
                target_denominator,
                evidence=activity.unit_conversion_evidence,
            ))
    except UnitConversionError as exc:
        return None, exc.reason_code
    except ValueError:
        return None, UNIT_SYNTAX_UNSUPPORTED
    dimensions = _evaluate_dimensions(activity, source, origin, material_class)
    weights = _proxy_weights(material_class) if origin == CandidateOrigin.PROXY else WEIGHTS_DIRECT
    score = round(sum(weights[key] * dimensions[key] for key in weights), 6)
    evidence_coverage, evidence_gaps = _evidence_coverage(activity, source, weights)
    reasons = [f"{key} match={value:.2f}" for key, value in dimensions.items()]
    if semantic_note:
        reasons.append(semantic_note)
    limitations = list(semantic_limitations)
    if origin == CandidateOrigin.PROXY:
        limitations.append("proxy value; validate technology and bill-of-materials applicability")
    if source.year is None:
        limitations.append("source year is unspecified")
    if source.geography is None:
        limitations.append("source geography is unspecified")
    if not source.declared_product:
        limitations.append("formal_admission_incomplete:declared_product")
    if not source.boundary and not source.boundary_modules:
        limitations.append("formal_admission_incomplete:boundary")
    if evidence_gaps:
        limitations.append("evidence gaps: " + ", ".join(evidence_gaps))
    match_strategy = source.metadata.get("match_strategy", LinkStrategy.EXACT.value)
    if origin == CandidateOrigin.PROXY:
        resolution_type = (
            ResolutionType.CLASS_TECHNICAL_PROXY
            if dimensions["process"] >= 0.65 and dimensions["material"] >= 0.5
            else ResolutionType.CLASS_GENERIC_PROXY
        )
    elif match_strategy == LinkStrategy.SYNONYM.value:
        resolution_type = ResolutionType.DIRECT_ALIAS
    elif match_strategy == LinkStrategy.RELATED.value:
        resolution_type = ResolutionType.CLASS_GENERIC_PROXY
    elif source.factor_unit.casefold().replace(" ", "") != candidate_factor_unit.casefold().replace(" ", ""):
        resolution_type = ResolutionType.UNIT_CONVERTED
    else:
        resolution_type = ResolutionType.DIRECT_EXACT
    candidate = Candidate(
        candidate_id=f"{origin.value}:{source.source_id}",
        origin=origin,
        source=source,
        provenance=source.provenance,
        factor_value=value,
        factor_unit=candidate_factor_unit,
        score=score,
        reasons=tuple(reasons),
        limitations=tuple(dict.fromkeys(limitations)),
        dimensions=dimensions,
        proxy_material=source.material_name if origin == CandidateOrigin.PROXY else None,
        proxy_class=material_class.name if origin == CandidateOrigin.PROXY and material_class else None,
        evidence_coverage=evidence_coverage,
        evidence_gaps=evidence_gaps,
        resolution_type=resolution_type,
        base_source_ids=(source.source_id,),
        resolved_activity_value=resolved_quantity,
        resolved_activity_unit=(
            parse_factor_unit(candidate_factor_unit).activity_unit.canonical_unit
            if resolved_quantity is not None else None
        ),
        activity_dimension=activity.activity_dimension,
        resolved_quantity_kg=(
            resolved_quantity if activity.activity_dimension == ActivityDimension.MASS.value else None
        ),
        total_emissions_kgco2e=(
            resolved_quantity * value if resolved_quantity is not None else None
        ),
    )
    return finalize_candidate(candidate), None


async def evaluate_records(
    activity: NormalizedActivity,
    records: Sequence[SourceRecord],
    origin: CandidateOrigin,
    understanding: MaterialUnderstandingPort,
    material_class: MaterialClass | None = None,
    qualification_sink: list[CandidateQualification] | None = None,
    admission_sink: list[CandidateAdmission] | None = None,
    observation_sink: list[RecallObservation] | None = None,
    registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY,
) -> tuple[tuple[Candidate, ...], tuple[CandidateExclusion, ...]]:
    candidates: list[Candidate] = []
    exclusions: list[CandidateExclusion] = []
    for raw_source in records:
        source = registry.enrich_source(raw_source)
        strategy = source.metadata.get("match_strategy", LinkStrategy.EXACT.value)
        policy = (
            QualificationPolicy.PROXY
            if origin == CandidateOrigin.PROXY
            else QualificationPolicy.RELATED
            if strategy == LinkStrategy.RELATED.value
            else QualificationPolicy.DIRECT
        )
        qualification = qualify_record(activity, source, policy, registry=registry)
        if qualification_sink is not None:
            qualification_sink.append(qualification)
        if admission_sink is not None:
            admission_exclusions = tuple(filter(None, (
                qualification.primary_exclusion, *qualification.additional_exclusions,
            )))
            admission_sink.append(CandidateAdmission(
                source_id=source.source_id,
                retrieval_strategy=LinkStrategy(strategy),
                admitted=qualification.eligible,
                observation_only=not qualification.eligible,
                identity_proof_ids=(
                    activity.identity_resolution.evidence_ids
                    if activity.identity_resolution else ()
                ),
                source_identity_rule_ids=tuple(filter(None,
                    source.metadata.get("material_rule_ids", "").split(",")
                )),
                hard_exclusions=admission_exclusions,
            ))
        if not qualification.eligible:
            if strategy == LinkStrategy.RELATED.value and observation_sink is not None:
                target_identity = activity.material_identity or _material_identity(
                    activity.canonical_name,
                    product_form=activity.product_form,
                    composition=activity.composition,
                    production_process=activity.production_process,
                    registry=registry,
                )
                source_identity = _source_identity(source, registry)
                retrieval_basis = (
                    (f"product form matched: {target_identity.product_form}",)
                    if target_identity.product_form
                    and source_identity.product_form == target_identity.product_form
                    else ("bounded material term recall",)
                )
                observation_sink.append(RecallObservation(
                    source_id=source.source_id, material_name=source.material_name,
                    retrieval_strategy=LinkStrategy.RELATED,
                    retrieval_basis=retrieval_basis,
                    identity_compatibility=qualification.identity.status.value,
                    factor_kind=source.factor_kind,
                    eligible_for_candidate_pool=False,
                    primary_exclusion=qualification.primary_exclusion,
                    additional_exclusions=qualification.additional_exclusions,
                ))
            exclusions.append(CandidateExclusion(
                source.source_id, origin,
                tuple(filter(None, (qualification.primary_exclusion, *qualification.additional_exclusions))) or ("record qualification failed",)
            ))
            continue
        assessment = await understanding.assess_candidate(activity, source, origin.value, material_class)
        if not assessment.eligible:
            reasons = tuple(filter(None, (assessment.note, *assessment.limitations))) or (
                "semantic assessment marked candidate ineligible",
            )
            exclusions.append(CandidateExclusion(source.source_id, origin, reasons))
            continue
        candidate, failure = _candidate(
            activity, source, origin, assessment.note, assessment.limitations, material_class
        )
        if candidate is not None:
            candidates.append(candidate)
        else:
            exclusions.append(CandidateExclusion(source.source_id, origin, (failure or "candidate conversion failed",)))
    return tuple(candidates), tuple(exclusions)


class ValidateNode(Node[GraphState]):
    name = "validate"

    async def run(self, state: GraphState) -> GraphState:
        # ResolutionRequest validates at construction; this event makes the
        # validation edge explicit in the graph audit trail.
        state.stage = Stage.VALIDATE
        state.event(Stage.VALIDATE, "request validated")
        return state


class NormalizeNode(Node[GraphState]):
    name = "normalize"

    def __init__(
        self,
        understanding: MaterialUnderstandingPort,
        registry: MaterialSemanticRegistryPort,
        suggestion_port: MaterialRuleSuggestionPort,
    ) -> None:
        self.understanding = understanding
        self.registry = registry
        self.suggestion_port = suggestion_port

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.NORMALIZE
        interpretation = await self.understanding.interpret(state.request)
        unit_reason_codes: list[str] = []
        quantity_kg = None
        quantity_base = None
        quantity_base_unit = None
        activity_dimension = None
        effective_target = state.request.target_factor_unit
        try:
            activity_unit = parse_activity_unit(state.request.quantity_unit)
            activity_dimension = activity_unit.dimension.value
            base_units = {
                ActivityDimension.MASS: "kg",
                ActivityDimension.ENERGY: "kWh",
                ActivityDimension.VOLUME: "m3",
                ActivityDimension.TRANSPORT_WORK: "tkm",
                ActivityDimension.COUNT: "item",
                ActivityDimension.AREA: "m2",
            }
            quantity_base_unit = base_units[activity_unit.dimension]
            if activity_unit.canonical_unit == "Nm3":
                # Keep a conditioned-volume request in its stated reference state.
                # The same directional evidence may be needed later to convert a
                # source factor into Nm3; pre-normalizing the quantity to m3 would
                # incorrectly demand the inverse evidence direction.
                quantity_base_unit = "Nm3"
                quantity_base = state.request.quantity
            else:
                quantity_base = float(convert_activity_decimal(
                    state.request.quantity,
                    state.request.quantity_unit,
                    quantity_base_unit,
                    evidence=state.request.unit_conversion_evidence,
                ))
            if activity_unit.dimension == ActivityDimension.MASS:
                quantity_kg = quantity_base
            if effective_target is None:
                effective_target = f"kgCO2e/{activity_unit.canonical_unit}"
            parsed_target = parse_factor_unit(effective_target)
            if parsed_target.activity_unit.dimension != activity_unit.dimension:
                unit_reason_codes.append(UNIT_DIMENSION_MISMATCH)
        except UnitConversionError as exc:
            unit_reason_codes.append(exc.reason_code)
        except ValueError:
            unit_reason_codes.append(UNIT_SYNTAX_UNSUPPORTED)
        if effective_target is None:
            effective_target = f"kgCO2e/{state.request.quantity_unit}"
        state.unit_reason_codes = tuple(dict.fromkeys(unit_reason_codes))
        canonical = normalize_text(interpretation.canonical_name)
        alias_fields = tuple(normalize_text(alias) for alias in interpretation.aliases)
        product_form = normalize_text(interpretation.product_form or state.request.product_form)
        canonical_product_form = _canonical_product_form(product_form.value)
        composition = normalize_text(interpretation.composition or state.request.composition)
        production_process = normalize_text(interpretation.production_process or state.request.production_process)
        registry_resolution = self.registry.resolve(
            canonical.value,
            product_form=canonical_product_form,
            composition=composition.value or None,
            production_process=production_process.value or None,
        )
        identity = registry_resolution.identity
        registry_suggestion = None
        if not registry_resolution.sufficiently_identified:
            registry_suggestion = await self.suggestion_port.suggest(canonical.value)
        canonical_product_form = identity.product_form or canonical_product_form
        resolved_process = production_process.value or (
            identity.manufacturing_route[0] if identity.manufacturing_route else None
        )
        subject_type = state.request.subject_type
        if subject_type == FactorSubjectType.UNKNOWN:
            raw_subject_text = state.request.material_name.casefold()
            if "raw material" in raw_subject_text or "原料" in raw_subject_text or "原矿" in raw_subject_text:
                subject_type = FactorSubjectType.RAW_MATERIAL
        request_gap_items: list[RequestGap] = []
        first_unresolved = identity.unresolved_attributes[:1]
        for field in first_unresolved:
            if (
                field in {"steel_fiber_type", "steel_grade_or_family", "surface_coating", "application"}
            ):
                request_gap_items.append(RequestGap(
                    gap_id=f"{state.request.request_id}:{field}",
                    gap_type=RequestGapType.INPUT_SPECIFICATION,
                    field=field,
                    reason="steel fiber is a broad product family; subtype is required before selecting an EPD",
                    required=True,
                    options=("ordinary_uncoated_carbon_steel", "copper_plated_steel", "heat_resistant_stainless_steel", "unknown"),
                ))
            elif field == "numeric_grade_basis":
                request_gap_items.append(RequestGap(
                    gap_id=f"{state.request.request_id}:{field}",
                    gap_type=RequestGapType.INPUT_SPECIFICATION,
                    field=field,
                    reason=(
                        "the numeric purity grade cannot be bound to one component of this "
                        "composite or unregistered material"
                    ),
                    required=True,
                    options=tuple((*identity.constituent_entity_ids, "unknown")),
                ))
            elif field == "product_variant":
                request_gap_items.append(RequestGap(
                    gap_id=f"{state.request.request_id}:{field}",
                    gap_type=RequestGapType.INPUT_SPECIFICATION,
                    field=field,
                    reason="the product-family label has multiple declared-product variants",
                    required=True,
                    options=("specific_declared_product", "unknown"),
                ))
        request_gaps = tuple(request_gap_items)
        boundary = normalize_text(state.request.boundary)
        input_name = normalize_text(state.request.material_name)
        normalized_fields = (input_name, canonical, *alias_fields, product_form, composition, production_process, boundary)
        rule_ids = list(dict.fromkeys(
            rule for field in normalized_fields for rule in field.applied_rule_ids
        ))
        if input_name.value != canonical.value:
            rule_ids.append("material_understanding.semantic_mapping/v1")
        state.normalized = NormalizedActivity(
            request_id=state.request.request_id,
            canonical_name=canonical.value,
            # Registry material aliases identify the head material; they are
            # not full-product synonyms and must not erase process/grade
            # qualifiers such as electrofused versus sintered.
            aliases=tuple(field.value for field in alias_fields if field.value),
            quantity_kg=quantity_kg,
            geography=state.request.geography,
            year=state.request.year,
            product_form=canonical_product_form,
            composition=composition.value or None,
            production_process=resolved_process,
            subject_type=subject_type,
            boundary=boundary.value,
            target_factor_unit=effective_target,
            normalization_rule_ids=tuple(dict.fromkeys(rule_ids)),
            original_quantity=state.request.quantity,
            original_quantity_unit=state.request.quantity_unit,
            material_identity=identity,
            request_gaps=request_gaps,
            semantic_registry_version=registry_resolution.registry_version,
            material_rule_ids=registry_resolution.material_rule_ids,
            process_rule_ids=registry_resolution.process_rule_ids,
            form_rule_ids=registry_resolution.form_rule_ids,
            relation_ids=registry_resolution.relation_ids,
            registry_suggestion=registry_suggestion,
            material_mention=registry_resolution.mention,
            identity_resolution=registry_resolution.identity_resolution,
            retrieval_intent=registry_resolution.retrieval_intent,
            quantity_base=quantity_base,
            quantity_base_unit=quantity_base_unit,
            activity_dimension=activity_dimension,
            unit_reason_codes=state.unit_reason_codes,
            unit_conversion_evidence=state.request.unit_conversion_evidence,
            target_factor_unit_derived=state.request.target_factor_unit is None,
        )
        state.trace.normalized_business_fingerprint = normalized_business_fingerprint(state.normalized)
        state.request_gaps = request_gaps
        if request_gaps and request_gaps[0].field != "numeric_grade_basis":
            state.provisional_options = (
                ProvisionalOption("ordinary_uncoated_reference", "steel subtype and coating are unknown"),
                ProvisionalOption("copper_plated_reference", "surface coating is unknown"),
                ProvisionalOption("ferritic_stainless_reference", "steel grade is unknown"),
            )
        state.request_resolution_plan = RequestResolutionPlan(
            request_id=state.request.request_id,
            gaps=request_gaps,
            next_question=request_gaps[0] if request_gaps else None,
            provisional_options=state.provisional_options,
        )
        state.event(Stage.NORMALIZE, "activity normalized; quantity converted to controlled base unit", {
            "input_material_name": state.request.material_name,
            "canonical_name": state.normalized.canonical_name,
            "quantity_kg": state.normalized.quantity_kg,
            "original_quantity": state.normalized.original_quantity,
            "original_quantity_unit": state.normalized.original_quantity_unit,
            "target_factor_unit": state.normalized.target_factor_unit,
            "effective_target_factor_unit": state.normalized.target_factor_unit,
            "target_factor_unit_derived": state.request.target_factor_unit is None,
            "quantity_base": state.normalized.quantity_base,
            "quantity_base_unit": state.normalized.quantity_base_unit,
            "activity_dimension": state.normalized.activity_dimension,
            "unit_reason_codes": state.unit_reason_codes,
            "normalization_rule_ids": state.normalized.normalization_rule_ids,
            "material_identity": identity.to_dict(),
            "material_mention": (
                registry_resolution.mention.to_dict() if registry_resolution.mention else None
            ),
            "identity_resolution": (
                registry_resolution.identity_resolution.to_dict()
                if registry_resolution.identity_resolution else None
            ),
            "retrieval_intent": (
                registry_resolution.retrieval_intent.to_dict()
                if registry_resolution.retrieval_intent else None
            ),
            "semantic_registry": {
                "version": registry_resolution.registry_version,
                "sha256": registry_resolution.registry_sha256,
                "material_rule_ids": registry_resolution.material_rule_ids,
                "process_rule_ids": registry_resolution.process_rule_ids,
                "form_rule_ids": registry_resolution.form_rule_ids,
                "relation_ids": registry_resolution.relation_ids,
                "sufficiently_identified": registry_resolution.sufficiently_identified,
                "draft_suggestion": registry_suggestion.to_dict() if registry_suggestion else None,
                "suggestion_requires_human_review": registry_suggestion is not None,
            },
            "request_gaps": tuple(gap.__dict__ if hasattr(gap, "__dict__") else {
                "gap_id": gap.gap_id, "gap_type": gap.gap_type.value, "field": gap.field,
                "reason": gap.reason, "required": gap.required, "options": gap.options,
            } for gap in request_gaps),
            "request_resolution_plan": state.request_resolution_plan.to_dict(),
            "raw_request_fingerprint": state.trace.raw_request_fingerprint,
            "normalized_business_fingerprint": state.trace.normalized_business_fingerprint,
        })
        return state


class LocalRetrievalNode(Node[GraphState]):
    name = "local_retrieval"

    def __init__(self, repository: FactorRepositoryPort) -> None:
        self.repository = repository

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.LOCAL_RETRIEVAL
        if state.normalized is None:
            return state
        if state.normalized.retrieval_intent is None:
            raise ValueError("normalized activity lacks RetrievalIntent")
        try:
            result = await self.repository.search(state.normalized.retrieval_intent)
        except CatalogIntegrityError as exc:
            if "SHA-256" in str(exc) or "signature" in str(exc):
                raise
            state.local_records = ()
            state.excluded_candidates.append(CandidateExclusion(
                source_id="local-catalog-integrity",
                origin=CandidateOrigin.LOCAL,
                reasons=("conflicting_duplicate_source_id",),
            ))
            state.event(Stage.LOCAL_RETRIEVAL, "local factor catalogue integrity conflict", {
                "reason_code": "CONFLICTING_DUPLICATE_SOURCE_ID",
                "exception_type": type(exc).__name__,
                "repository_type": type(self.repository).__name__,
                "record_count": 0,
            })
            return state
        except OSError as exc:
            # Catalogue transport failures are evidence about availability, not
            # permission to invent or admit a factor.  Keep the failure visible
            # through a stable reason code without reflecting exception text,
            # then let the existing graph reach its normal fail-closed result.
            state.local_records = ()
            state.event(Stage.LOCAL_RETRIEVAL, "local factor source unavailable", {
                "reason_code": type(exc).__name__,
                "repository_type": type(self.repository).__name__,
                "record_count": 0,
            })
            return state
        state.local_records = result.records
        state.link_attempts.extend(result.attempts)
        state.trace.set_database_anchor(result.database_anchor)
        state.semantic_index_anchor = result.semantic_index_anchor
        state.retrieval_diagnostics = result.retrieval_diagnostics
        state.conversion_diagnostics = result.conversion_diagnostics
        if result.funnel is not None:
            state.pipeline_funnel = result.funnel
        # Semantic-index observations already carry resolved entity evidence;
        # qualification may append exclusions without changing their source.
        state.recall_observations = result.observations
        state.event(Stage.LOCAL_RETRIEVAL, f"retrieved {len(state.local_records)} local source records", {
            "database_anchor": result.database_anchor.to_dict(),
            "semantic_index_anchor": (
                result.semantic_index_anchor.to_dict() if result.semantic_index_anchor else None
            ),
            "record_count": len(state.local_records),
            "records": tuple({
                "source_id": record.source_id,
                "material_name": record.material_name,
                "factor_value": record.factor_value,
                "factor_unit": record.factor_unit,
            } for record in state.local_records),
            "link_attempts": tuple(attempt.to_dict() for attempt in result.attempts),
            "raw_related_hits": tuple(record.source_id for record in state.local_records
                                       if record.metadata.get("match_strategy") == LinkStrategy.RELATED.value),
            "recall_observations": tuple(observation.to_dict() for observation in state.recall_observations),
            "retrieval_diagnostics": tuple(item.to_dict() for item in state.retrieval_diagnostics),
            "conversion_diagnostics": tuple(item.to_dict() for item in state.conversion_diagnostics),
            "pipeline_funnel": state.pipeline_funnel.to_dict(),
        })
        return state


class LocalEvaluateNode(Node[GraphState]):
    name = "local_evaluate"

    def __init__(
        self,
        understanding: MaterialUnderstandingPort,
        registry: MaterialSemanticRegistryPort,
    ) -> None:
        self.understanding = understanding
        self.registry = registry

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.LOCAL_EVALUATE
        if state.normalized is not None:
            qualifications: list[CandidateQualification] = []
            admissions: list[CandidateAdmission] = []
            observations: list[RecallObservation] = list(state.recall_observations)
            exclusions: tuple[CandidateExclusion, ...] = ()
            selected_by_id: dict[str, Candidate] = {}
            for strategy in (LinkStrategy.EXACT, LinkStrategy.SYNONYM, LinkStrategy.RELATED):
                layer = tuple(
                    record for record in state.local_records
                    if record.metadata.get("match_strategy", LinkStrategy.EXACT.value) == strategy.value
                )
                if not layer:
                    continue
                layer_candidates, layer_exclusions = await evaluate_records(
                    state.normalized,
                    layer,
                    CandidateOrigin.LOCAL,
                    self.understanding,
                    qualification_sink=qualifications,
                    admission_sink=admissions,
                    observation_sink=observations,
                    registry=self.registry,
                )
                exclusions = (*exclusions, *layer_exclusions)
                for candidate in layer_candidates:
                    selected_by_id.setdefault(candidate.candidate_id, candidate)
            # Exact, reviewed aliases and same-entity Related records form one
            # qualification pool. Exact is a ranking signal, never permission
            # to hide a decisive ambiguity carried by another channel.
            state.local_candidates = tuple(selected_by_id.values())
            state.qualifications = tuple(qualifications)
            dimensions = (
                "identity", "factor_kind", "subject_type", "source_quality",
                "indicator", "declared_product", "boundary", "unit",
            )
            state.qualification_diagnostics = tuple(
                QualificationDiagnostic(
                    source_id=item.source_id,
                    dimension=dimension,
                    status=getattr(item, dimension).status.value,
                    reason_codes=getattr(item, dimension).reasons,
                )
                for item in state.qualifications
                for dimension in dimensions
            )
            request_unit_diagnostics: tuple[dict[str, object], ...] = tuple({
                "source_id": "request",
                "reason_code": code,
                "source_unit": state.request.quantity_unit,
                "target_unit": state.normalized.target_factor_unit,
            } for code in state.unit_reason_codes)
            record_unit_diagnostics: tuple[dict[str, object], ...] = tuple({
                "source_id": item.source_id,
                "reason_code": reason,
                "source_unit": next(
                    (record.factor_unit for record in state.local_records if record.source_id == item.source_id),
                    None,
                ),
                "target_unit": state.normalized.target_factor_unit,
            }
            for item in state.qualifications
            for reason in item.unit.reasons
            if reason in {
                UNIT_SYNTAX_UNSUPPORTED,
                CATALOG_FACTOR_UNIT_INVALID,
                UNIT_DIMENSION_MISMATCH,
                UNIT_CONVERSION_EVIDENCE_REQUIRED,
            })
            state.unit_conversion_diagnostics = (
                *request_unit_diagnostics,
                *record_unit_diagnostics,
            )
            state.candidate_admissions = tuple(admissions)
            state.recall_observations = tuple(observations)
            state.excluded_candidates.extend(exclusions)
            state.resolution_candidates = state.local_candidates
            if state.normalized.subject_type == FactorSubjectType.UNKNOWN:
                operational_subjects = tuple(dict.fromkeys(
                    OPERATIONAL_FACTOR_SUBJECTS.get(record.factor_kind) or record.subject_type
                    for record in state.local_records
                    if (
                        OPERATIONAL_FACTOR_SUBJECTS.get(record.factor_kind)
                        or record.subject_type in EXPLICIT_NON_MATERIAL_SUBJECTS
                    )
                ))
                if operational_subjects:
                    subject_gap = RequestGap(
                        gap_id=f"{state.request.request_id}:subject_type",
                        gap_type=RequestGapType.INPUT_SPECIFICATION,
                        field="subject_type",
                        reason="an operational factor requires an explicit compatible subject type",
                        required=True,
                        options=tuple(subject.value for subject in operational_subjects),
                    )
                    state.request_gaps = tuple((*state.request_gaps, subject_gap))
                    state.request_resolution_plan = RequestResolutionPlan(
                        request_id=state.request.request_id,
                        gaps=state.request_gaps,
                        next_question=state.request_gaps[0],
                        provisional_options=state.provisional_options,
                    )
            identity_resolution = state.normalized.identity_resolution
            if (
                identity_resolution
                and identity_resolution.sufficiently_resolved
                and identity_resolution.selected_product_entity_id is None
            ):
                route_aliases = {
                    "primary": "primary",
                    "primary aluminium production": "primary",
                    "secondary recycling": "secondary",
                    "secondary aluminium production": "secondary",
                    "recycled aluminium production": "secondary",
                }
                product_routes = {
                    "mat.product.primary_aluminium": "primary",
                    "mat.product.secondary_aluminium": "secondary",
                }
                variant_values: list[str] = []
                for candidate in state.local_candidates:
                    variant = (
                        product_routes.get(candidate.source.metadata.get("product_entity_id", ""))
                        or route_aliases.get(_text(candidate.source.production_process))
                    )
                    if variant is not None:
                        variant_values.append(variant)
                variants = tuple(dict.fromkeys(variant_values))
                if len(variants) > 1:
                    route_gap = RequestGap(
                        gap_id=f"{state.request.request_id}:route",
                        gap_type=RequestGapType.INPUT_SPECIFICATION,
                        field="route",
                        reason=(
                            "the generic material identity has multiple product-route variants; "
                            "select a route before choosing a factor"
                        ),
                        required=True,
                        options=variants + ("unknown",),
                    )
                    state.request_gaps = tuple((*state.request_gaps, route_gap))
                    state.request_resolution_plan = RequestResolutionPlan(
                        request_id=state.request.request_id,
                        gaps=state.request_gaps,
                        next_question=state.request_gaps[0],
                        provisional_options=state.provisional_options,
                    )
        state.event(Stage.LOCAL_EVALUATE, f"evaluated {len(state.local_candidates)} local candidates", {
            "candidate_ids": tuple(candidate.candidate_id for candidate in state.local_candidates),
            "excluded": tuple({"source_id": item.source_id, "reasons": item.reasons} for item in state.excluded_candidates),
            "record_qualifications": tuple(item.to_dict() for item in state.qualifications),
            "qualification_diagnostics": tuple(
                item.to_dict() for item in state.qualification_diagnostics
            ),
            "candidate_admissions": tuple(item.to_dict() for item in state.candidate_admissions),
            "raw_related_hits": tuple(item.to_dict() for item in state.recall_observations),
        })
        return state


class GapAnalysisNode(Node[GraphState]):
    name = "gap_analysis"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.GAP_ANALYSIS
        analyzed: list[Candidate] = []
        if state.normalized is not None:
            for candidate in state.resolution_candidates:
                gaps = analyze_candidate_gaps(state.normalized, candidate)
                state.gaps[candidate.candidate_id] = gaps
                analyzed.append(finalize_candidate(replace(candidate, gaps=gaps)))
        state.resolution_candidates = tuple(analyzed)
        state.local_candidates = state.resolution_candidates
        state.event(Stage.GAP_ANALYSIS, "candidate gaps analyzed structurally", {
            "candidate_gaps": tuple({
                "candidate_id": candidate.candidate_id,
                "gaps": tuple(gap.to_dict() for gap in candidate.gaps),
            } for candidate in state.resolution_candidates),
        })
        return state


class ResolutionPlannerNode(Node[GraphState]):
    name = "resolution_planner"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.RESOLUTION_PLANNER
        for candidate in state.resolution_candidates:
            aliases = {
                "unit": RouterType.UNIT_SCALE,
                "reference_flow": RouterType.REFERENCE_FLOW,
                "process": RouterType.PROCESS_VARIANT,
                "grade": RouterType.GRADE_COMPOSITION,
                "proxy": RouterType.CLASS_AWARE_PROXY,
            }
            preferred_order = tuple(
                aliases[item]
                for item in (
                    part.strip().casefold()
                    for part in candidate.source.metadata.get("resolution_order", "").split(",")
                )
                if item in aliases
            )
            state.resolution_plans[candidate.candidate_id] = build_resolution_plan(
                candidate.candidate_id, candidate.gaps, preferred_order
            )
        state.event(Stage.RESOLUTION_PLANNER, "deterministic resolution plans created", {
            "plans": tuple(plan.to_dict() for plan in state.resolution_plans.values()),
        })
        return state


class UnitScaleResolutionNode(Node[GraphState]):
    name = "unit_scale_resolution"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.UNIT_SCALE_RESOLUTION
        if state.normalized is None:
            return state
        output = tuple(resolve_unit_scale(state.normalized, candidate) for candidate in state.resolution_candidates)
        state.resolution_candidates = output
        state.event(Stage.UNIT_SCALE_RESOLUTION, "deterministic activity and factor unit scales resolved", {
            "candidates": tuple({
                "candidate_id": candidate.candidate_id,
                "resolution_type": candidate.resolution_type.value,
                "steps": tuple(step.to_dict() for step in candidate.transformation_steps),
            } for candidate in output),
        })
        return state


class ReferenceFlowResolutionNode(Node[GraphState]):
    name = "reference_flow_resolution"

    def __init__(self, repository: ReferenceFlowRepositoryPort) -> None:
        self.repository = repository

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.REFERENCE_FLOW_RESOLUTION
        if state.normalized is None:
            return state
        needs_resolution = any(
            any(gap.gap_type == GapType.REFERENCE_FLOW for gap in candidate.gaps)
            for candidate in state.resolution_candidates
        )
        if not needs_resolution:
            return state
        state.reference_flow_records = tuple(await self.repository.search(state.normalized))
        state.parameter_evidence.extend(record.evidence for record in state.reference_flow_records)
        output: list[Candidate] = []
        for candidate in state.resolution_candidates:
            needs = any(gap.gap_type == GapType.REFERENCE_FLOW for gap in candidate.gaps)
            if not needs:
                output.append(candidate)
                continue
            resolved = resolve_reference_flow(state.normalized, candidate, state.reference_flow_records)
            if not resolved:
                state.required_fields = _reference_flow_required_fields(state.normalized.original_quantity_unit)
                state.warnings.append(
                    f"reference-flow conversion lacks evidence for {state.normalized.original_quantity_unit}"
                )
                continue
            output.extend(
                replace(item, gaps=tuple(gap for gap in item.gaps if gap.gap_type != GapType.REFERENCE_FLOW))
                for item in resolved
            )
        state.resolution_candidates = tuple(output)
        state.event(Stage.REFERENCE_FLOW_RESOLUTION, "reference-flow scenarios resolved", {
            "record_ids": tuple(record.record_id for record in state.reference_flow_records),
            "candidate_ids": tuple(candidate.candidate_id for candidate in state.resolution_candidates),
            "required_fields": state.required_fields,
        })
        return state


class ProcessVariantResolutionNode(Node[GraphState]):
    name = "process_variant_resolution"

    def __init__(self, repository: ProcessParameterRepositoryPort) -> None:
        self.repository = repository

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.PROCESS_VARIANT_RESOLUTION
        if state.normalized is None:
            return state
        output: list[Candidate] = []
        modes: list[dict[str, str]] = []
        current_evidence: list[ParameterEvidence] = []
        for candidate in state.resolution_candidates:
            needs = any(gap.gap_type == GapType.PROCESS_VARIANT for gap in candidate.gaps)
            if not needs:
                output.append(candidate)
                continue
            evidence = tuple(await self.repository.search(state.normalized, candidate.source))
            state.parameter_evidence.extend(evidence)
            current_evidence.extend(evidence)
            for assignment in resolve_process_accounting_assignments(
                state.normalized.canonical_name, evidence
            ):
                if assignment not in state.accounting_assignments:
                    state.accounting_assignments.append(assignment)
            try:
                resolved, mode = resolve_process_variant(candidate, evidence)
            except ValueError as exc:
                state.warnings.append(str(exc))
                resolved, mode = resolve_process_variant(candidate, ())
                resolved = replace(resolved, warnings=resolved.warnings + (str(exc),))
            if resolved.resolution_type == ResolutionType.PROCESS_ADJUSTED:
                resolved = replace(resolved, gaps=tuple(
                    gap for gap in resolved.gaps if gap.gap_type != GapType.PROCESS_VARIANT
                ))
            output.append(resolved)
            modes.append({"candidate_id": resolved.candidate_id, "mode": mode.value})
        state.resolution_candidates = tuple(output)
        state.event(Stage.PROCESS_VARIANT_RESOLUTION, "process variants resolved with sourced parameters", {
            "modes": tuple(modes),
            "parameter_ids": tuple(item.parameter_id for item in current_evidence),
            "parameter_evidence": tuple(item.to_dict() for item in current_evidence),
            "parameter_databases": _parameter_database_anchors(current_evidence),
            "warnings": tuple(state.warnings),
            "accounting_assignments": tuple(
                item.to_dict() for item in state.accounting_assignments
            ),
        })
        return state


class GradeCompositionResolutionNode(Node[GraphState]):
    name = "grade_composition_resolution"

    def __init__(
        self,
        repository: GradeSeriesRepositoryPort,
        registry: MaterialSemanticRegistryPort,
    ) -> None:
        self.repository = repository
        self.registry = registry

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.GRADE_COMPOSITION_RESOLUTION
        if state.normalized is None:
            return state
        output: list[Candidate] = []
        for candidate in state.resolution_candidates:
            needs = any(gap.gap_type == GapType.GRADE_COMPOSITION for gap in candidate.gaps)
            if not needs:
                output.append(candidate)
                continue
            recalled = (candidate.source, *tuple(await self.repository.search(state.normalized, candidate.source)))
            qualified: list[SourceRecord] = []
            for raw_anchor in recalled:
                anchor = self.registry.enrich_source(raw_anchor)
                qualification = qualify_record(
                    state.normalized,
                    anchor,
                    QualificationPolicy.GRADE_ANCHOR,
                    reference=candidate.source,
                    registry=self.registry,
                )
                state.qualifications = (*state.qualifications, qualification)
                if qualification.eligible:
                    qualified.append(anchor)
                elif anchor.source_id != candidate.source.source_id:
                    state.excluded_candidates.append(CandidateExclusion(
                        anchor.source_id,
                        candidate.origin,
                        tuple(filter(None, (
                            qualification.primary_exclusion,
                            *qualification.additional_exclusions,
                        ))) or ("grade anchor qualification failed",),
                    ))
            resolved = resolve_grade(state.normalized, candidate, tuple(qualified))
            if resolved.resolution_type in {
                ResolutionType.GRADE_EXACT_ANCHOR,
                ResolutionType.GRADE_INTERPOLATED,
                ResolutionType.GRADE_ADJUSTED,
            }:
                resolved = replace(resolved, gaps=tuple(
                    gap for gap in resolved.gaps if gap.gap_type != GapType.GRADE_COMPOSITION
                ))
            output.append(resolved)
        state.resolution_candidates = tuple(output)
        state.event(Stage.GRADE_COMPOSITION_RESOLUTION, "grade and composition gaps resolved", {
            "candidates": tuple({
                "candidate_id": candidate.candidate_id,
                "resolution_type": candidate.resolution_type.value,
                "base_source_ids": candidate.base_source_ids,
            } for candidate in state.resolution_candidates),
        })
        return state


class MaterialResolutionNode(Node[GraphState]):
    name = "material_resolution"

    def __init__(self, understanding: MaterialUnderstandingPort) -> None:
        self.understanding = understanding

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.MATERIAL_RESOLUTION
        if state.normalized is not None:
            state.material_class = await self.understanding.classify(state.normalized)
        state.event(Stage.MATERIAL_RESOLUTION, f"material class resolved: {state.material_class.name if state.material_class else 'none'}", {
            "material_class": state.material_class.name if state.material_class else None,
            "family": state.material_class.family if state.material_class else None,
            "category": state.material_class.category.value if state.material_class else None,
            "rationale": state.material_class.rationale if state.material_class else None,
        })
        return state


class ProxyResolutionNode(Node[GraphState]):
    name = "proxy_resolution"

    def __init__(self, repository: ProxyRepositoryPort) -> None:
        self.repository = repository

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.PROXY_RESOLUTION
        if state.normalized is not None and state.material_class is not None:
            state.proxy_records = tuple(await self.repository.search(state.normalized, state.material_class))
        state.link_attempts.append(LinkAttempt(
            LinkStrategy.CLASS_AWARE_PROXY,
            LinkOutcome.NO_MATCH if not state.proxy_records else LinkOutcome.MATCHED if len(state.proxy_records) == 1 else LinkOutcome.CANDIDATE_SET,
            tuple(record.source_id for record in state.proxy_records),
            "proxy retrieval constrained by the resolved material class and later suitability gates",
        ))
        state.event(Stage.PROXY_RESOLUTION, f"retrieved {len(state.proxy_records)} proxy source records", {
            "record_count": len(state.proxy_records),
            "records": tuple({"source_id": record.source_id, "material_name": record.material_name} for record in state.proxy_records),
            "link_attempt": state.link_attempts[-1].to_dict(),
        })
        return state


class ProxyEvaluateNode(Node[GraphState]):
    name = "proxy_evaluate"

    def __init__(
        self,
        understanding: MaterialUnderstandingPort,
        registry: MaterialSemanticRegistryPort,
    ) -> None:
        self.understanding = understanding
        self.registry = registry

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.PROXY_EVALUATE
        if state.normalized is not None:
            qualifications: list[CandidateQualification] = []
            admissions: list[CandidateAdmission] = []
            observations: list[RecallObservation] = list(state.recall_observations)
            state.proxy_candidates, exclusions = await evaluate_records(
                state.normalized, state.proxy_records, CandidateOrigin.PROXY, self.understanding, state.material_class,
                qualification_sink=qualifications, observation_sink=observations,
                admission_sink=admissions,
                registry=self.registry,
            )
            state.qualifications = tuple((*state.qualifications, *qualifications))
            state.candidate_admissions = tuple((*state.candidate_admissions, *admissions))
            state.recall_observations = tuple(observations)
            state.proxy_candidates = tuple(
                finalize_candidate(replace(
                    candidate,
                    gaps=analyze_candidate_gaps(state.normalized, candidate),
                ))
                for candidate in state.proxy_candidates
            )
            state.excluded_candidates.extend(exclusions)
        state.event(Stage.PROXY_EVALUATE, f"evaluated {len(state.proxy_candidates)} proxy candidates", {
            "candidate_ids": tuple(candidate.candidate_id for candidate in state.proxy_candidates),
            "candidate_gaps": tuple({
                "candidate_id": candidate.candidate_id,
                "gaps": tuple(gap.to_dict() for gap in candidate.gaps),
            } for candidate in state.proxy_candidates),
            "excluded": tuple({"source_id": item.source_id, "reasons": item.reasons} for item in state.excluded_candidates),
        })
        return state


class ReEvaluateNode(Node[GraphState]):
    name = "re_evaluate"

    def __init__(self, min_score: float) -> None:
        self.min_score = min_score

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.RE_EVALUATE
        state.resolution_candidates = tuple(
            finalize_candidate(candidate, min_score=self.min_score)
            for candidate in state.resolution_candidates
        )
        state.proxy_candidates = tuple(
            finalize_candidate(candidate, min_score=self.min_score)
            for candidate in state.proxy_candidates
        )
        all_candidates = state.resolution_candidates + state.proxy_candidates
        state.transformation_steps = [
            step for candidate in all_candidates for step in candidate.transformation_steps
        ]
        state.assumptions = list(dict.fromkeys(
            assumption for candidate in all_candidates for assumption in candidate.assumptions
        ))
        state.warnings = list(dict.fromkeys((
            *state.warnings,
            *(warning for candidate in all_candidates for warning in candidate.warnings),
        )))
        state.derived_candidates = [
            to_derived(candidate) for candidate in all_candidates
            if candidate.transformation_steps
            or candidate.resolution_type not in {
                ResolutionType.DIRECT_EXACT,
                ResolutionType.DIRECT_ALIAS,
                ResolutionType.UNIT_CONVERTED,
            }
        ]
        state.event(Stage.RE_EVALUATE, "resolved candidates re-evaluated and lineage assembled", {
            "derived_candidate_ids": tuple(item.candidate_id for item in state.derived_candidates),
            "transformation_steps": tuple(step.to_dict() for step in state.transformation_steps),
            "assumptions": tuple(state.assumptions),
            "warnings": tuple(state.warnings),
        })
        return state


class CandidatePoolNode(Node[GraphState]):
    name = "candidate_pool"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.CANDIDATE_POOL
        # Derived scenarios may share one source ID and must remain distinct.
        by_id: dict[str, Candidate] = {}
        for candidate in state.resolution_candidates + state.proxy_candidates:
            previous = by_id.get(candidate.candidate_id)
            if previous is None or candidate.resolution_strength > previous.resolution_strength:
                by_id[candidate.candidate_id] = candidate
        state.candidate_pool = tuple(by_id.values())
        state.pipeline_funnel = replace(
            state.pipeline_funnel,
            qualified_records=sum(item.eligible for item in state.qualifications),
            candidate_pool=len(state.candidate_pool),
        )
        state.event(Stage.CANDIDATE_POOL, f"candidate pool contains {len(state.candidate_pool)} candidates", {
            "candidate_ids": tuple(candidate.candidate_id for candidate in state.candidate_pool),
        })
        return state


class RankNode(Node[GraphState]):
    name = "rank"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.RANK
        state.ranked_candidates = tuple(
            sorted(state.candidate_pool, key=lambda c: (
                TYPE_PRIORITY[c.resolution_type],
                _applicability_rank(c),
                _source_priority_rank(c),
                -c.resolution_strength,
                -c.score,
                -c.evidence_coverage,
                len(c.assumptions),
                c.source.source_id,
                c.candidate_id,
            ))
        )
        state.pipeline_funnel = replace(
            state.pipeline_funnel, ranked_candidates=len(state.ranked_candidates)
        )
        state.event(Stage.RANK, "candidates ranked by resolution type, strength, evidence and stable lineage", {
            "ranking": tuple({
                "rank": index,
                "candidate_id": candidate.candidate_id,
                "source_id": candidate.source.source_id,
                "origin": candidate.origin.value,
                "score": candidate.score,
                "evidence_coverage": candidate.evidence_coverage,
                "resolution_type": candidate.resolution_type.value,
                "result_tier": candidate.result_tier.value,
                "resolution_strength": candidate.resolution_strength,
                "assumption_count": len(candidate.assumptions),
                "source_priority_rank": _source_priority_rank(candidate),
                "source_priority_issue": candidate.source.metadata.get(
                    "source_priority_issue", ""
                ),
            } for index, candidate in enumerate(state.ranked_candidates, start=1)),
        })
        return state


class TopKNode(Node[GraphState]):
    name = "top_k"

    async def run(self, state: GraphState) -> GraphState:
        state.stage = Stage.TOP_K
        stable_unit_codes = (
            UNIT_SYNTAX_UNSUPPORTED,
            CATALOG_FACTOR_UNIT_INVALID,
            UNIT_DIMENSION_MISMATCH,
            UNIT_CONVERSION_EVIDENCE_REQUIRED,
        )
        observed_unit_codes = set(state.unit_reason_codes)
        observed_unit_codes.update(
            reason
            for item in state.qualifications
            for reason in item.unit.reasons
            if reason in stable_unit_codes
        )
        observed_unit_codes.update(
            reason
            for item in state.excluded_candidates
            for reason in item.reasons
            if reason in stable_unit_codes
        )
        reason_codes = tuple(code for code in stable_unit_codes if code in observed_unit_codes)
        source_document_hash_required = any(
            SOURCE_DOCUMENT_HASH_REQUIRED in item.source_quality.reasons
            for item in state.qualifications
        )
        if source_document_hash_required:
            reason_codes = (*reason_codes, SOURCE_DOCUMENT_HASH_REQUIRED)
        admission_rejected = bool(state.qualifications) and not any(
            item.eligible for item in state.qualifications
        )
        if admission_rejected and not reason_codes and not state.request_gaps:
            reason_codes = (*reason_codes, "ADMISSION_REJECTED")
        conflicting_external_id = any(
            "conflicting_duplicate_source_id" in item.reasons
            for item in state.excluded_candidates
        )
        if conflicting_external_id:
            reason_codes = (*reason_codes, "CONFLICTING_DUPLICATE_SOURCE_ID")
        grade_specification_conflict = any(
            "unresolved_grade_or_specification_conflict"
            in candidate_hard_rejection_reasons(candidate)
            for candidate in state.ranked_candidates
        )
        if grade_specification_conflict:
            reason_codes = (*reason_codes, "GRADE_SPECIFICATION_CONFLICT")
        process_model_conflict = any(
            "unresolved_process_variant_requires_process_model"
            in candidate_hard_rejection_reasons(candidate)
            for candidate in state.ranked_candidates
        )
        if UNIT_CONVERSION_EVIDENCE_REQUIRED in reason_codes:
            state.required_fields = tuple(dict.fromkeys((
                *state.required_fields,
                "unit_conversion_evidence",
            )))
        eligible = tuple(c for c in state.ranked_candidates if candidate_is_sufficient(c, state))
        reviewable = tuple(
            candidate
            for candidate in state.ranked_candidates
            if not candidate_hard_rejection_reasons(candidate)
            and candidate.result_tier == ResultTier.REFERENCE_ONLY
        )
        candidate_ambiguity_fields: list[str] = []
        if state.normalized is not None and not state.request_gaps:
            ambiguity_by_id = {
                candidate.candidate_id: candidate
                for candidate in (*eligible, *reviewable)
            }
            ambiguity_pool = tuple(ambiguity_by_id.values())
            decisive_fields = (
                ("production_process", state.normalized.production_process),
                ("product_form", state.normalized.product_form),
                ("geography", state.normalized.geography),
                ("year", state.normalized.year),
            )
            for field_name, requested_value in decisive_fields:
                observed_values = {
                    getattr(candidate.source, field_name)
                    for candidate in ambiguity_pool
                    if getattr(candidate.source, field_name) not in (None, "")
                }
                if requested_value in (None, "") and len(observed_values) > 1:
                    candidate_ambiguity_fields.append(field_name)
            if candidate_ambiguity_fields:
                state.required_fields = tuple(dict.fromkeys((
                    *state.required_fields,
                    *candidate_ambiguity_fields,
                )))
                reason_by_field = {
                    "production_process": "PROCESS_REQUIRED",
                    "product_form": "PRODUCT_FORM_REQUIRED",
                    "geography": "GEOGRAPHY_REQUIRED",
                    "year": "YEAR_REQUIRED",
                }
                reason_codes = tuple(dict.fromkeys((
                    *reason_codes,
                    *(reason_by_field[field] for field in candidate_ambiguity_fields),
                )))
                reviewable = tuple(
                    replace(
                        candidate,
                        result_tier=ResultTier.REFERENCE_ONLY,
                        limitations=tuple(dict.fromkeys((
                            *candidate.limitations,
                            "candidate requires a decisive request attribute before selection",
                        ))),
                    )
                    for candidate in ambiguity_pool
                )
                eligible = ()
        if state.request_gaps:
            # Discovery candidates remain in Trace, but incomplete request
            # identity can never silently become a selectable recommendation.
            # Otherwise-qualified REFERENCE_ONLY candidates remain visible for
            # explicit review and cannot use the standard approval mode.
            eligible = ()
        if state.unit_reason_codes:
            eligible = ()
            reviewable = ()
        reviewable_reasons = {
            candidate.candidate_id: candidate_rejection_reasons(candidate, state)
            for candidate in reviewable[: state.request.top_k]
        }
        diagnostics = tuple(
            candidate
            for candidate in state.ranked_candidates
            if candidate_hard_rejection_reasons(candidate)
        )[: state.request.top_k]
        if state.normalized is not None and not state.accounting_assignments:
            state.accounting_assignments.append(resolve_accounting_assignment(
                state.normalized.canonical_name,
                quantified=bool(eligible or reviewable),
            ))
        diagnostic_gaps = tuple({
            gap.gap_id: gap
            for candidate in diagnostics
            for gap in candidate.gaps
        }.values())
        assignment_by_role: dict[
            tuple[str, AccountingRole, tuple[AccountingModule, ...]], AccountingAssignment
        ] = {}
        for item in state.accounting_assignments:
            key = (item.subject, item.role, item.modules)
            previous = assignment_by_role.get(key)
            if (
                previous is None
                or item.quantification_status == AccountingQuantificationStatus.QUANTIFIED
                and previous.quantification_status
                != AccountingQuantificationStatus.QUANTIFIED
            ):
                assignment_by_role[key] = item
        unique_assignments = tuple(assignment_by_role.values())
        has_user_selectable_output = bool(eligible or reviewable)
        unresolved_gaps = diagnostic_gaps if not has_user_selectable_output else ()
        question_items: list[str] = []
        ambiguity_questions = {
            "production_process": "请确认目标生产工艺或路线。",
            "product_form": "请确认目标产品形态或规格。",
            "geography": "请确认目标适用地域。",
            "year": "请确认目标适用年份。",
        }
        question_items.extend(
            ambiguity_questions[field] for field in candidate_ambiguity_fields
        )
        if any(gap.gap_type == GapType.PROCESS_VARIANT for gap in unresolved_gaps):
            question_items.extend((
                "请补充目标工艺路线的综合能耗及能源分配。",
                "请补充电极、焦炭或还原剂等含碳耗材的用量、含碳率与氧化率；没有则明确填零。",
                "请确认参考因子是否包含需要被替换的原工艺过程。",
            ))
        if not has_user_selectable_output and any(
            "process-emission" in warning or "stoichiometric" in warning
            for warning in state.warnings
        ):
            question_items.append("现有证据触发了过程排放，但计算参数不完整，请补齐后再生成目标因子。")
        questions = tuple(dict.fromkeys(question_items))
        known_exclusions = {(item.candidate_id, item.source_id) for item in state.excluded_candidates}
        for candidate in state.ranked_candidates:
            reasons = candidate_rejection_reasons(candidate, state)
            admission_key = (candidate.candidate_id, candidate.source.source_id)
            if reasons and admission_key not in known_exclusions:
                state.excluded_candidates.append(CandidateExclusion(
                    source_id=candidate.source.source_id,
                    origin=candidate.origin,
                    reasons=reasons,
                    candidate_id=candidate.candidate_id,
                ))
        if eligible:
            top = eligible[: state.request.top_k]
            from .models import Recommendation, ResolutionStatus

            state.recommendation = Recommendation(
                request_id=state.request.request_id,
                status=ResolutionStatus.RECOMMENDATION_READY,
                candidates=top,
                message="top-k factor candidates ready for human approval",
                trace=state.trace,
                confidence=calibrate_confidence(eligible),
                resolution_strength=calibrate_confidence(eligible),
                reviewable_candidates=reviewable[: state.request.top_k],
                reviewable_candidate_reasons=reviewable_reasons,
                diagnostic_candidates=diagnostics,
                missing_gaps=unresolved_gaps,
                questions=questions,
                accounting_assignments=unique_assignments,
                reason_codes=reason_codes,
            )
        else:
            from .models import FollowUp, Recommendation, ResolutionStatus

            # Soft-review candidates may be shown for explicit override. Hard
            # diagnostics remain only in Trace/exclusions and are never returned.
            reviewable_top = reviewable[: state.request.top_k]
            top = ()
            if UNIT_CONVERSION_EVIDENCE_REQUIRED in reason_codes:
                follow_up = FollowUp.MORE_INPUT
                status = ResolutionStatus.MORE_INPUT_NEEDED
            elif UNIT_SYNTAX_UNSUPPORTED in reason_codes or UNIT_DIMENSION_MISMATCH in reason_codes:
                follow_up = FollowUp.UNRESOLVED
                status = ResolutionStatus.UNRESOLVED
            elif CATALOG_FACTOR_UNIT_INVALID in reason_codes:
                follow_up = FollowUp.DATA_GOVERNANCE
                status = ResolutionStatus.UNRESOLVED
            elif "CONFLICTING_DUPLICATE_SOURCE_ID" in reason_codes:
                follow_up = FollowUp.DATA_GOVERNANCE
                status = ResolutionStatus.UNRESOLVED
            elif state.required_fields:
                follow_up = FollowUp.MORE_INPUT
                status = ResolutionStatus.MORE_INPUT_NEEDED
                top = ()
            elif reviewable_top:
                follow_up = FollowUp.DATA_GOVERNANCE
                status = ResolutionStatus.REFERENCE_REVIEW_REQUIRED
            elif process_model_conflict:
                follow_up = FollowUp.PROCESS_MODEL
                status = ResolutionStatus.PROCESS_MODEL_REQUIRED
            elif "GRADE_SPECIFICATION_CONFLICT" in reason_codes:
                follow_up = FollowUp.DATA_GOVERNANCE
                status = ResolutionStatus.UNRESOLVED
            elif any(
                candidate_hard_rejection_reasons(candidate)
                for candidate in state.ranked_candidates
            ):
                follow_up = FollowUp.PROCESS_MODEL
                status = ResolutionStatus.PROCESS_MODEL_REQUIRED
            elif admission_rejected:
                follow_up = FollowUp.DATA_GOVERNANCE
                status = ResolutionStatus.UNRESOLVED
            else:
                follow_up = FollowUp.SUPPLIER_DATA
                status = ResolutionStatus.SUPPLIER_DATA_REQUIRED
            state.recommendation = Recommendation(
                request_id=state.request.request_id,
                status=status,
                candidates=top,
                follow_up=follow_up,
                message=(
                    "required input specification is missing; choose a material subtype before selecting a factor"
                    if state.request_gaps
                    else "multiple qualified records require a decisive request attribute before selection"
                    if candidate_ambiguity_fields
                    else "mathematically required reference-flow evidence is missing"
                    if state.required_fields and not state.request_gaps
                    else (
                        f"found {len(reviewable_top)} traceable reference candidate(s); "
                        "explicit reference override and review rationale are required"
                    )
                    if reviewable_top
                    else (
                        f"未找到可直接使用的目标工艺因子；已保留 {len(diagnostics)} 个"
                        "参考候选及其排除原因，请补齐工艺 Gap 后重新计算"
                    )
                    if diagnostics
                    else "no traceable candidate could be resolved; continue with the indicated follow-up"
                ),
                trace=state.trace,
                reviewable_candidates=reviewable_top,
                reviewable_candidate_reasons=reviewable_reasons,
                diagnostic_candidates=diagnostics,
                missing_gaps=unresolved_gaps,
                questions=questions,
                accounting_assignments=unique_assignments,
                reason_codes=reason_codes,
            )
            if not state.required_fields and not reviewable_top:
                state.link_attempts.append(LinkAttempt(
                    LinkStrategy.UNRESOLVED,
                    LinkOutcome.NO_MATCH,
                    tuple(candidate.source.source_id for candidate in state.ranked_candidates),
                    "all local and proxy strategies exhausted without a traceable resolvable candidate",
                ))
        state.stage = Stage.TERMINAL
        state.pipeline_funnel = replace(
            state.pipeline_funnel, returned_candidates=len(top)
        )
        state.event(Stage.TOP_K, f"returned {len(top)} top-k candidates with status {state.recommendation.status.value}", {
            "selected_candidate_ids": tuple(candidate.candidate_id for candidate in top),
            "diagnostic_candidate_ids": tuple(
                candidate.candidate_id for candidate in diagnostics
            ),
            "reviewable_candidate_ids": tuple(
                candidate.candidate_id
                for candidate in state.recommendation.reviewable_candidates
            ),
            "reviewable_candidate_reasons": reviewable_reasons,
            "missing_gaps": tuple(gap.to_dict() for gap in unresolved_gaps),
            "questions": questions,
            "accounting_assignments": tuple(
                item.to_dict() for item in unique_assignments
            ),
            "status": state.recommendation.status.value,
            "confidence": state.recommendation.confidence.to_dict() if state.recommendation.confidence else None,
            "resolution_strength": (
                state.recommendation.resolution_strength.to_dict()
                if state.recommendation.resolution_strength else None
            ),
            "required_fields": state.required_fields,
            "reason_codes": reason_codes,
            "conversion_diagnostics": state.unit_conversion_diagnostics,
            "material_identity": state.normalized.material_identity.to_dict() if state.normalized and state.normalized.material_identity else None,
            "request_gaps": tuple({
                "gap_id": gap.gap_id, "gap_type": gap.gap_type.value, "field": gap.field,
                "reason": gap.reason, "required": gap.required, "options": gap.options,
            } for gap in state.request_gaps),
            "required_choice": ({
                "field": state.request_gaps[0].field, "options": state.request_gaps[0].options,
            } if state.request_gaps else None),
            "provisional_options": tuple({
                "option_type": option.option_type,
                "not_selected_because": option.not_selected_because,
            } for option in state.provisional_options),
            "request_resolution_plan": state.request_resolution_plan.to_dict() if state.request_resolution_plan else None,
            "raw_related_hits": tuple(observation.to_dict() for observation in state.recall_observations),
            "record_qualifications": tuple(item.to_dict() for item in state.qualifications),
            "candidate_admissions": tuple(item.to_dict() for item in state.candidate_admissions),
            "qualification_diagnostics": tuple(
                item.to_dict() for item in state.qualification_diagnostics
            ),
            "transformation_steps": tuple(step.to_dict() for step in state.transformation_steps),
            "link_attempts": tuple(attempt.to_dict() for attempt in state.link_attempts),
            "excluded": tuple({
                "candidate_id": item.candidate_id,
                "source_id": item.source_id,
                "origin": item.origin.value,
                "reasons": item.reasons,
            } for item in state.excluded_candidates),
            "pipeline_funnel": state.pipeline_funnel.to_dict(),
        })
        return state
