"""Policy-driven record qualification shared by Direct, Proxy and Grade anchors."""

from __future__ import annotations

import json
from dataclasses import replace

from .matching import normalize_text
from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    CandidateQualification,
    FactorKind,
    FactorSubjectType,
    LinkStrategy,
    MaterialCategory,
    MaterialIdentity,
    NormalizedActivity,
    QualificationDimension,
    QualificationPolicy,
    QualificationStatus,
    SourceQualityStatus,
    SourceRecord,
)
from .units import (
    CATALOG_FACTOR_UNIT_INVALID,
    UNIT_DIMENSION_MISMATCH,
    UNIT_SYNTAX_UNSUPPORTED,
    CatalogFactorUnitError,
    UnitSyntaxError,
    convert_factor,
    parse_catalog_factor_unit,
    parse_factor_unit,
    plan_factor_conversion,
)


def text(value: str | None) -> str:
    return normalize_text(value).value


def material_identity(
    name: str,
    *,
    product_form: str | None = None,
    composition: str | None = None,
    production_process: str | None = None,
    registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY,
) -> MaterialIdentity:
    """Resolve identity through the shared, versioned semantic registry."""

    return registry.resolve(
        name,
        product_form=product_form,
        composition=composition,
        production_process=production_process,
    ).identity


def source_identity(
    source: SourceRecord,
    registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY,
) -> MaterialIdentity:
    category = source.metadata.get("material_category", "")
    identity = material_identity(
        source.material_name,
        product_form=source.product_form,
        composition=source.composition,
        production_process=source.production_process,
        registry=registry,
    )
    if category:
        try:
            identity = replace(identity, category=MaterialCategory(category))
        except ValueError:
            pass
    return identity


def _dimension(status: QualificationStatus, *reasons: str) -> QualificationDimension:
    return QualificationDimension(status, tuple(reason for reason in reasons if reason))


OPERATIONAL_FACTOR_SUBJECTS = {
    FactorKind.ENERGY_FACTOR: FactorSubjectType.ENERGY,
    FactorKind.COMBUSTION_FACTOR: FactorSubjectType.ENERGY,
    FactorKind.TRANSPORT_FACTOR: FactorSubjectType.TRANSPORT,
}
EXPLICIT_NON_MATERIAL_SUBJECTS = frozenset({
    FactorSubjectType.ENERGY,
    FactorSubjectType.TRANSPORT,
    FactorSubjectType.PROCESS,
    FactorSubjectType.WASTE,
})


def qualify_record(
    activity: NormalizedActivity,
    source: SourceRecord,
    policy: QualificationPolicy = QualificationPolicy.DIRECT,
    *,
    reference: SourceRecord | None = None,
    registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY,
) -> CandidateQualification:
    """Apply common semantic gates and policy-specific identity/series rules."""

    request_target = activity.material_identity or material_identity(
        activity.canonical_name,
        product_form=activity.product_form,
        composition=activity.composition,
        production_process=activity.production_process,
        registry=registry,
    )
    target = (
        source_identity(reference, registry)
        if policy == QualificationPolicy.GRADE_ANCHOR and reference is not None
        else request_target
    )
    observed = source_identity(source, registry)
    identity_reasons: list[str] = []
    hard_identity_exclusions: list[str] = []
    strategy = source.metadata.get("match_strategy", "exact_link")
    exact_primary_name = text(activity.canonical_name) == text(source.material_name)
    raw_aliases = source.metadata.get("aliases", "")
    try:
        parsed_aliases = json.loads(raw_aliases) if isinstance(raw_aliases, str) else raw_aliases
    except json.JSONDecodeError:
        parsed_aliases = ()
    source_aliases = (
        {text(str(alias)) for alias in parsed_aliases}
        if isinstance(parsed_aliases, (list, tuple))
        else set()
    )
    reviewed_alias_match = (
        strategy == LinkStrategy.SYNONYM.value
        and text(activity.canonical_name) in source_aliases
    )

    def compare_identity(field: str, target_value: object, observed_value: object, *, always_hard: bool) -> None:
        if target_value in (None, "") or observed_value in (None, "") or target_value == observed_value:
            return
        identity_reasons.append(f"{field} {observed_value!s} is not {target_value!s}")
        if always_hard or policy != QualificationPolicy.PROXY:
            hard_identity_exclusions.append(f"{field}_mismatch")

    same_base_entity = bool(
        target.base_entity_id
        and observed.base_entity_id
        and target.base_entity_id == observed.base_entity_id
    )
    if not same_base_entity:
        compare_identity(
            "material_category",
            None if target.category == MaterialCategory.UNKNOWN else target.category.value,
            None if observed.category == MaterialCategory.UNKNOWN else observed.category.value,
            always_hard=True,
        )
    compare_identity(
        "base_entity_id",
        target.base_entity_id,
        observed.base_entity_id,
        always_hard=True,
    )
    if policy == QualificationPolicy.RELATED:
        if not target.base_entity_id or not observed.base_entity_id:
            identity_reasons.append("same-entity Related retrieval requires resolved request and source entity IDs")
            hard_identity_exclusions.append("identity_proof_missing")
        elif target.base_entity_id != observed.base_entity_id:
            identity_reasons.append(
                f"Related source entity {observed.base_entity_id} is not request entity {target.base_entity_id}"
            )
            hard_identity_exclusions.append("base_entity_id_mismatch")
    elif policy == QualificationPolicy.DIRECT and not target.base_entity_id and not observed.base_entity_id:
        if (exact_primary_name and strategy == LinkStrategy.EXACT.value) or reviewed_alias_match:
            # A formal catalogue primary-name exact match is valid for this
            # Direct record only; it does not enable Related or Proxy recall.
            pass
        else:
            identity_reasons.append("Direct candidate lacks entity proof or exact primary-name identity")
            hard_identity_exclusions.append("identity_proof_missing")
    compare_identity("material_family", target.material_family, observed.material_family, always_hard=False)
    compare_identity("head_material", target.head_material, observed.head_material, always_hard=False)
    compare_identity(
        "product_entity_id",
        target.product_entity_id,
        observed.product_entity_id,
        always_hard=True,
    )
    if target.product_entity_id and not observed.product_entity_id:
        identity_reasons.append("source product_entity_id is missing for a product-specific request")
        hard_identity_exclusions.append("product_entity_id_missing")
    compare_identity(
        "product_form",
        target.product_form,
        observed.product_form,
        always_hard=False,
    )
    identity_status = (
        QualificationStatus.MISMATCH
        if identity_reasons
        else QualificationStatus.PASS
        if observed.base_entity_id or exact_primary_name or reviewed_alias_match or target.category != MaterialCategory.UNKNOWN
        else QualificationStatus.UNKNOWN
    )

    expected_operational_subject = OPERATIONAL_FACTOR_SUBJECTS.get(source.factor_kind)
    if source.factor_kind == FactorKind.EMISSION_LIMIT:
        kind_dim = _dimension(QualificationStatus.MISMATCH, "emission limit is not an A1 lifecycle factor")
    elif source.factor_kind in {
        FactorKind.LIFECYCLE_FACTOR,
        FactorKind.EPD_INDICATOR,
        FactorKind.DERIVED_PROXY_FACTOR,
        *OPERATIONAL_FACTOR_SUBJECTS,
    }:
        kind_dim = _dimension(QualificationStatus.PASS)
    else:
        kind_dim = _dimension(QualificationStatus.UNKNOWN, "factor kind is not explicitly classified")

    if expected_operational_subject and source.subject_type != expected_operational_subject:
        subject_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"{source.factor_kind.value} requires subject {expected_operational_subject.value!r}",
        )
    elif expected_operational_subject and activity.subject_type == FactorSubjectType.UNKNOWN:
        subject_dim = _dimension(
            QualificationStatus.UNKNOWN,
            f"request subject must be {expected_operational_subject.value!r} for {source.factor_kind.value}",
        )
    elif (
        activity.subject_type == FactorSubjectType.UNKNOWN
        and source.subject_type in EXPLICIT_NON_MATERIAL_SUBJECTS
    ):
        subject_dim = _dimension(
            QualificationStatus.UNKNOWN,
            f"request subject must explicitly confirm {source.subject_type.value!r}",
        )
    elif (
        activity.subject_type != FactorSubjectType.UNKNOWN
        and source.subject_type != FactorSubjectType.UNKNOWN
        and activity.subject_type != source.subject_type
    ):
        subject_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"factor subject {source.subject_type.value!r} is not request subject {activity.subject_type.value!r}",
        )
    elif source.subject_type == FactorSubjectType.UNKNOWN:
        subject_dim = _dimension(QualificationStatus.UNKNOWN, "factor subject type is unspecified")
    else:
        subject_dim = _dimension(QualificationStatus.PASS)

    if not source.admission_eligible or source.source_quality_status == SourceQualityStatus.REJECTED:
        quality_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"source quality status {source.source_quality_status.value} is not admission eligible",
        )
    elif source.source_quality_status == SourceQualityStatus.NEEDS_REVIEW:
        quality_dim = _dimension(QualificationStatus.UNKNOWN, "source quality requires human review")
    else:
        quality_dim = _dimension(QualificationStatus.PASS)

    if source.indicator in ("GWP-total", "gwp-total"):
        indicator_dim = _dimension(QualificationStatus.PASS)
    elif source.indicator in (None, ""):
        indicator_dim = _dimension(QualificationStatus.UNKNOWN, "factor indicator is unspecified")
    else:
        indicator_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"indicator {source.indicator!r} is not GWP-total",
        )

    declared_identity = (
        material_identity(source.declared_product, registry=registry)
        if source.declared_product else None
    )
    declared_entity_compatible = bool(
        declared_identity
        and target.base_entity_id
        and declared_identity.base_entity_id == target.base_entity_id
        and (
            not target.product_entity_id
            or not declared_identity.product_entity_id
            or declared_identity.product_entity_id == target.product_entity_id
        )
    )
    if not source.declared_product:
        declared_dim = _dimension(QualificationStatus.UNKNOWN, "declared product is unspecified")
    elif (
        text(target.canonical_name) in text(source.declared_product)
        or text(source.declared_product) in text(target.canonical_name)
        or declared_entity_compatible
        or reviewed_alias_match
    ):
        declared_dim = _dimension(QualificationStatus.PASS)
    else:
        declared_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"declared product {source.declared_product!r} is not compatible with {target.canonical_name!r}",
        )

    target_boundary = text(activity.boundary).replace(" ", "-")
    boundary_aliases = {
        "a1": frozenset({"A1"}),
        "a2": frozenset({"A2"}),
        "a3": frozenset({"A3"}),
        "a1-a3": frozenset({"A1", "A2", "A3"}),
        "a1–a3": frozenset({"A1", "A2", "A3"}),
        "cradle-to-gate": frozenset({"A1", "A2", "A3"}),
    }
    required_modules = boundary_aliases.get(target_boundary)
    observed_modules = {str(module).strip().upper() for module in source.boundary_modules if str(module).strip()}
    if required_modules is None:
        boundary_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"unsupported request boundary {activity.boundary!r}",
        )
    elif observed_modules:
        boundary_dim = (
            _dimension(QualificationStatus.PASS)
            if required_modules is not None and required_modules == observed_modules
            else _dimension(
                QualificationStatus.MISMATCH,
                f"boundary modules {sorted(observed_modules)!r} are not exact request modules "
                f"{sorted(required_modules) if required_modules is not None else [activity.boundary]!r}",
            )
        )
    elif source.boundary:
        observed_boundary = text(source.boundary).replace(" ", "-")
        equivalent = observed_boundary == target_boundary or (
            required_modules == frozenset({"A1", "A2", "A3"})
            and observed_boundary in {"a1-a3", "a1–a3", "cradle-to-gate"}
        )
        boundary_dim = (
            _dimension(QualificationStatus.PASS)
            if equivalent
            else _dimension(
                QualificationStatus.MISMATCH,
                f"boundary {source.boundary!r} is not compatible with {activity.boundary!r}",
            )
        )
    else:
        boundary_dim = _dimension(QualificationStatus.UNKNOWN, "boundary is unspecified")

    parsed_unit = None
    unit_exclusion = None
    try:
        parsed_unit = parse_catalog_factor_unit(source.factor_unit)
        parse_factor_unit(activity.target_factor_unit)
        conversion = plan_factor_conversion(
            source.factor_unit,
            activity.target_factor_unit,
            evidence=activity.unit_conversion_evidence,
        )
        reference_flow_bridge = bool(
            conversion.reason_code == UNIT_DIMENSION_MISMATCH
            and activity.target_factor_unit_derived
            and (
                activity.activity_dimension == "COUNT"
                or activity.activity_dimension == "VOLUME" and bool(activity.product_form)
            )
            and parsed_unit.activity_unit.dimension.value == "MASS"
        )
        if reference_flow_bridge:
            unit_dim = _dimension(QualificationStatus.PASS, "reference_flow_resolution_required")
        elif conversion.reason_code:
            unit_exclusion = conversion.reason_code
            unit_dim = _dimension(QualificationStatus.MISMATCH, conversion.reason_code)
        else:
            unit_dim = _dimension(QualificationStatus.PASS)
        if parsed_unit.reference_product_qualifier and declared_dim.status != QualificationStatus.PASS:
            if not source.declared_product:
                declared_dim = _dimension(
                    QualificationStatus.MISMATCH,
                    "reference-product qualifier requires a declared product",
                )
            unit_dim = _dimension(
                QualificationStatus.UNKNOWN,
                "product qualifier requires a compatible declared product",
            )
    except CatalogFactorUnitError:
        unit_exclusion = CATALOG_FACTOR_UNIT_INVALID
        unit_dim = _dimension(QualificationStatus.MISMATCH, CATALOG_FACTOR_UNIT_INVALID)
    except UnitSyntaxError:
        unit_exclusion = UNIT_SYNTAX_UNSUPPORTED
        unit_dim = _dimension(QualificationStatus.MISMATCH, UNIT_SYNTAX_UNSUPPORTED)

    exclusions = list(hard_identity_exclusions)
    if kind_dim.status == QualificationStatus.MISMATCH:
        exclusions.append("factor_kind_mismatch")
    if subject_dim.status != QualificationStatus.PASS and (
        activity.subject_type != FactorSubjectType.UNKNOWN
        or expected_operational_subject
        or source.subject_type in EXPLICIT_NON_MATERIAL_SUBJECTS
    ):
        exclusions.append("subject_type_mismatch")
    if quality_dim.status != QualificationStatus.PASS:
        exclusions.append("source_quality_not_admissible")
    if indicator_dim.status == QualificationStatus.MISMATCH:
        exclusions.append("indicator_mismatch")
    if declared_dim.status == QualificationStatus.MISMATCH and policy == QualificationPolicy.DIRECT:
        exclusions.append("declared_product_mismatch")
    if boundary_dim.status == QualificationStatus.MISMATCH:
        exclusions.append("boundary_mismatch")
    if (
        parsed_unit
        and parsed_unit.reference_product_qualifier
        and declared_dim.status != QualificationStatus.PASS
        and policy != QualificationPolicy.GRADE_ANCHOR
    ):
        exclusions.append("unit_qualifier_requires_validation")
    if unit_dim.status == QualificationStatus.MISMATCH:
        exclusions.append(unit_exclusion or UNIT_SYNTAX_UNSUPPORTED)

    policy_checks: dict[str, QualificationDimension] = {}
    if policy == QualificationPolicy.GRADE_ANCHOR:
        if reference is None:
            raise ValueError("grade-anchor qualification requires a reference record")
        reference_product = reference.declared_product or reference.material_name
        if source.declared_product and (
            text(reference_product) in text(source.declared_product)
            or text(source.declared_product) in text(reference_product)
        ):
            declared_dim = _dimension(QualificationStatus.PASS)
        else:
            declared_dim = _dimension(
                QualificationStatus.MISMATCH,
                "grade anchor declared product is missing or incompatible with the reference series",
            )
        source_series = text(source.metadata.get("series_id") or source.metadata.get("series"))
        reference_series = text(reference.metadata.get("series_id") or reference.metadata.get("series"))
        policy_checks["series_id"] = (
            _dimension(QualificationStatus.PASS)
            if source_series and source_series == reference_series
            else _dimension(QualificationStatus.MISMATCH, "grade anchor requires an explicit matching series_id")
        )
        policy_checks["provider"] = (
            _dimension(QualificationStatus.PASS)
            if source.provider == reference.provider
            else _dimension(QualificationStatus.MISMATCH, "grade anchor provider differs from the reference")
        )
        policy_checks["process"] = (
            _dimension(QualificationStatus.PASS)
            if text(source.production_process)
            and text(source.production_process) == text(reference.production_process)
            else _dimension(QualificationStatus.MISMATCH, "grade anchor process is missing or incompatible")
        )
        reference_grade_schema = text(reference.metadata.get("grade_schema_id"))
        reference_grade_basis = text(reference.metadata.get("grade_basis_component_id"))
        if reference_grade_schema or reference_grade_basis:
            policy_checks["grade_schema"] = (
                _dimension(QualificationStatus.PASS)
                if text(source.metadata.get("grade_schema_id")) == reference_grade_schema
                and text(source.metadata.get("grade_basis_component_id")) == reference_grade_basis
                else _dimension(
                    QualificationStatus.MISMATCH,
                    "grade anchor schema or chemical basis differs from the reference",
                )
            )
        try:
            convert_factor(1.0, source.factor_unit, reference.factor_unit)
            policy_checks["reference_unit"] = _dimension(QualificationStatus.PASS)
        except ValueError as exc:
            policy_checks["reference_unit"] = _dimension(QualificationStatus.MISMATCH, str(exc))
        strict_dimensions = {
            "factor_kind": kind_dim,
            "source_quality": quality_dim,
            "indicator": indicator_dim,
            "declared_product": declared_dim,
            "boundary": boundary_dim,
            "unit": unit_dim,
            **policy_checks,
        }
        for name, dimension in strict_dimensions.items():
            if dimension.status != QualificationStatus.PASS:
                exclusions.append(f"grade_anchor_{name}_mismatch")

    exclusions = list(dict.fromkeys(exclusions))
    return CandidateQualification(
        source_id=source.source_id,
        identity=_dimension(identity_status, *identity_reasons),
        factor_kind=kind_dim,
        subject_type=subject_dim,
        source_quality=quality_dim,
        indicator=indicator_dim,
        declared_product=declared_dim,
        boundary=boundary_dim,
        unit=unit_dim,
        eligible=not exclusions,
        policy=policy,
        policy_checks=policy_checks,
        primary_exclusion=exclusions[0] if exclusions else None,
        additional_exclusions=tuple(exclusions[1:]),
    )
