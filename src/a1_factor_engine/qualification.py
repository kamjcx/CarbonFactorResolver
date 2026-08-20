"""Policy-driven record qualification shared by Direct, Proxy and Grade anchors."""

from __future__ import annotations

from dataclasses import replace

from .matching import normalize_text
from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    CandidateQualification,
    FactorKind,
    MaterialCategory,
    MaterialIdentity,
    NormalizedActivity,
    QualificationDimension,
    QualificationPolicy,
    QualificationStatus,
    SourceRecord,
)
from .units import convert_factor, parse_factor_unit


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
        if exact_primary_name and strategy == "exact_link":
            # A formal catalogue primary-name exact match is valid for this
            # Direct record only; it does not enable Related or Proxy recall.
            pass
        else:
            identity_reasons.append("Direct candidate lacks entity proof or exact primary-name identity")
            hard_identity_exclusions.append("identity_proof_missing")
    compare_identity("material_family", target.material_family, observed.material_family, always_hard=False)
    compare_identity("head_material", target.head_material, observed.head_material, always_hard=False)
    identity_status = (
        QualificationStatus.MISMATCH
        if identity_reasons
        else QualificationStatus.PASS
        if observed.base_entity_id or exact_primary_name or target.category != MaterialCategory.UNKNOWN
        else QualificationStatus.UNKNOWN
    )

    if source.factor_kind == FactorKind.EMISSION_LIMIT:
        kind_dim = _dimension(QualificationStatus.MISMATCH, "emission limit is not an A1 lifecycle factor")
    elif source.factor_kind in {
        FactorKind.LIFECYCLE_FACTOR,
        FactorKind.EPD_INDICATOR,
        FactorKind.DERIVED_PROXY_FACTOR,
    }:
        kind_dim = _dimension(QualificationStatus.PASS)
    else:
        kind_dim = _dimension(QualificationStatus.UNKNOWN, "factor kind is not explicitly classified")

    if source.indicator in ("GWP-total", "gwp-total"):
        indicator_dim = _dimension(QualificationStatus.PASS)
    elif source.indicator in (None, ""):
        indicator_dim = _dimension(QualificationStatus.UNKNOWN, "factor indicator is unspecified")
    else:
        indicator_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"indicator {source.indicator!r} is not GWP-total",
        )

    if not source.declared_product:
        declared_dim = _dimension(QualificationStatus.UNKNOWN, "declared product is unspecified")
    elif (
        text(target.canonical_name) in text(source.declared_product)
        or text(source.declared_product) in text(target.canonical_name)
        or (target.head_material and target.head_material == observed.head_material)
    ):
        declared_dim = _dimension(QualificationStatus.PASS)
    else:
        declared_dim = _dimension(
            QualificationStatus.MISMATCH,
            f"declared product {source.declared_product!r} is not compatible with {target.canonical_name!r}",
        )

    target_boundary = text(activity.boundary).replace(" ", "-")
    required_modules: set[str] = set()
    if target_boundary in {"cradle-to-gate", "a1-a3", "a1–a3"}:
        required_modules = {"A1", "A2", "A3"}
    elif target_boundary == "a1":
        required_modules = {"A1"}
    observed_modules = {str(module).strip().upper() for module in source.boundary_modules if str(module).strip()}
    if observed_modules:
        boundary_dim = (
            _dimension(QualificationStatus.PASS)
            if not required_modules or required_modules.issubset(observed_modules)
            else _dimension(
                QualificationStatus.MISMATCH,
                f"boundary modules {sorted(observed_modules)!r} do not cover {sorted(required_modules)!r}",
            )
        )
    elif source.boundary:
        observed_boundary = text(source.boundary).replace(" ", "-")
        equivalent = observed_boundary == target_boundary or (
            required_modules == {"A1", "A2", "A3"}
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
    try:
        parsed_unit = parse_factor_unit(source.factor_unit)
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
    except ValueError as exc:
        unit_dim = _dimension(QualificationStatus.MISMATCH, str(exc))

    exclusions = list(hard_identity_exclusions)
    if kind_dim.status == QualificationStatus.MISMATCH:
        exclusions.append("factor_kind_mismatch")
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
        exclusions.append("unit_syntax_mismatch")

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
        try:
            convert_factor(1.0, source.factor_unit, reference.factor_unit)
            policy_checks["reference_unit"] = _dimension(QualificationStatus.PASS)
        except ValueError as exc:
            policy_checks["reference_unit"] = _dimension(QualificationStatus.MISMATCH, str(exc))
        strict_dimensions = {
            "factor_kind": kind_dim,
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
