from __future__ import annotations

import json
from dataclasses import replace

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    AccountingModule,
    AccountingQuantificationStatus,
    AccountingRole,
    ApprovalMode,
    CandidateOrigin,
    CatalogDatasetPolicy,
    CatalogPolicyBundle,
    DatabaseVersionAnchor,
    EnergyConversionRecord,
    EnergyQuotaRecord,
    EnterpriseEnergyProfileRecord,
    EnterpriseProcessEmissionRecord,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    GapType,
    IdentityOutcome,
    LinkOutcome,
    LinkStrategy,
    MaterialCategory,
    MaterialRule,
    NumericTokenRole,
    ParameterEvidence,
    ParameterSourceType,
    ReferenceFlowRecord,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    ResolutionRequest,
    ResolutionStatus,
    ResolutionType,
    ResultTier,
    ScopedProcessParameterRecord,
    SemanticRole,
    SourceQualityStatus,
    SourceRecord,
    SqliteEnergyProcessParameterRepository,
    VersionedMaterialSemanticRegistry,
    create_energy_database,
    explicit_process_emission_observation,
    interpret_process_emission_observation,
    resolve_accounting_assignment,
    resolve_process_accounting_assignments,
    stoichiometric_carbon_emission_kgco2e_per_kg,
)
from a1_factor_engine.adapters import (
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
    InMemoryGradeSeriesRepository,
    InMemoryProcessParameterRepository,
    InMemoryProxyRepository,
    InMemoryReferenceFlowRepository,
)
from a1_factor_engine.integrity import catalog_content_sha256
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import NormalizedActivity, resolution_request_fingerprint
from a1_factor_engine.qualification import qualify_record
from a1_factor_engine.units import convert_factor, convert_mass, parse_factor_unit


@pytest.mark.parametrize(
    ("request_boundary", "source_modules", "expected"),
    [
        (request, source, request == source)
        for request in ("A1", "A2", "A3", "A1-A3")
        for source in ("A1", "A2", "A3", "A1-A3")
    ],
)
def test_lifecycle_boundary_matrix_is_exact(
    request_boundary: str, source_modules: str, expected: bool
) -> None:
    modules = ("A1", "A2", "A3") if source_modules == "A1-A3" else (source_modules,)
    activity = NormalizedActivity(
        request_id="boundary-matrix",
        canonical_name="High Alumina Brick",
        aliases=(),
        quantity_kg=1000.0,
        geography=None,
        year=2025,
        product_form=None,
        composition=None,
        production_process=None,
        subject_type=FactorSubjectType.FINISHED_PRODUCT,
        boundary=request_boundary,
        target_factor_unit="kgCO2e/t",
    )
    source = SourceRecord(
        source_id=f"source-{source_modules}",
        source_type=FactorSourceType.EPD,
        provider="issuer",
        locator="evidence://source",
        material_name="High Alumina Brick",
        factor_value=1.0,
        factor_unit="kgCO2e/t",
        factor_kind=FactorKind.EPD_INDICATOR,
        subject_type=FactorSubjectType.FINISHED_PRODUCT,
        source_quality_status=SourceQualityStatus.VERIFIED,
        admission_eligible=True,
        indicator="GWP-total",
        declared_product="High Alumina Brick",
        boundary="cradle-to-gate" if source_modules == "A1-A3" else source_modules,
        boundary_modules=modules,
    )

    qualification = qualify_record(activity, source)

    assert qualification.boundary.status.value == ("pass" if expected else "mismatch")
    assert qualification.eligible is expected


def test_subject_and_source_quality_are_hard_qualification_dimensions() -> None:
    activity = NormalizedActivity(
        request_id="raw-material",
        canonical_name="alumina",
        aliases=(), quantity_kg=1000.0, geography=None, year=2025,
        product_form=None, composition=None, production_process=None,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        boundary="A1", target_factor_unit="kgCO2e/t",
    )
    finished_product = SourceRecord(
        source_id="finished-product", source_type=FactorSourceType.EPD,
        provider="issuer", locator="evidence://finished", material_name="alumina",
        factor_value=1.0, factor_unit="kgCO2e/t", factor_kind=FactorKind.EPD_INDICATOR,
        subject_type=FactorSubjectType.FINISHED_PRODUCT,
        indicator="GWP-total", declared_product="alumina", boundary="A1", boundary_modules=("A1",),
    )
    rejected_source = replace(
        finished_product,
        source_id="rejected-source",
        subject_type=FactorSubjectType.RAW_MATERIAL,
        source_quality_status=SourceQualityStatus.REJECTED,
        admission_eligible=False,
    )

    subject_result = qualify_record(activity, finished_product)
    quality_result = qualify_record(activity, rejected_source)

    assert subject_result.subject_type.status.value == "mismatch"
    assert subject_result.primary_exclusion == "subject_type_mismatch"
    assert quality_result.source_quality.status.value == "mismatch"
    assert quality_result.primary_exclusion == "source_quality_not_admissible"


def test_electricity_entity_allows_compatible_declared_product_descriptor_difference() -> None:
    activity = NormalizedActivity(
        request_id="structured-energy",
        canonical_name="dawn synthetic electricity",
        aliases=(), quantity_kg=None, geography=None, year=2025,
        product_form=None, composition=None, production_process=None,
        subject_type=FactorSubjectType.ENERGY,
        boundary="A1-A3", target_factor_unit="kgCO2e/kWh",
    )
    source = SourceRecord(
        source_id="structured-energy", source_type=FactorSourceType.LOCAL_DATABASE,
        provider="synthetic", locator="evidence://structured-energy",
        material_name="dawn synthetic electricity", factor_value=0.412,
        factor_unit="kgCO2e/kWh", factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.ENERGY,
        indicator="GWP-total", declared_product="dawn electricity",
        boundary="cradle-to-gate", boundary_modules=("A1", "A2", "A3"),
        metadata={"match_strategy": LinkStrategy.EXACT.value},
    )

    result = qualify_record(activity, source)

    assert result.declared_product.status.value == "pass"
    assert result.eligible is True


def test_electricity_entity_does_not_accept_a_different_energy_carrier() -> None:
    activity = NormalizedActivity(
        request_id="structured-negative",
        canonical_name="dawn synthetic electricity",
        aliases=(), quantity_kg=None, geography=None, year=2025,
        product_form=None, composition=None, production_process=None,
        subject_type=FactorSubjectType.ENERGY,
        boundary="A1-A3", target_factor_unit="kgCO2e/kWh",
    )
    source = SourceRecord(
        source_id="structured-negative", source_type=FactorSourceType.LOCAL_DATABASE,
        provider="synthetic", locator="evidence://structured-negative",
        material_name="dawn synthetic electricity", factor_value=0.412,
        factor_unit="kgCO2e/kWh", factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.ENERGY,
        indicator="GWP-total", declared_product="dawn synthetic gas",
        boundary="cradle-to-gate", boundary_modules=("A1", "A2", "A3"),
        metadata={"match_strategy": LinkStrategy.EXACT.value},
    )

    result = qualify_record(activity, source)

    assert result.declared_product.status.value == "mismatch"
    assert result.eligible is False
    assert "declared_product_mismatch" in {
        result.primary_exclusion, *result.additional_exclusions,
    }


def test_explicit_subject_request_rejects_source_with_unknown_subject() -> None:
    activity = NormalizedActivity(
        request_id="unknown-subject",
        canonical_name="alumina",
        aliases=(), quantity_kg=1000.0, geography=None, year=2025,
        product_form=None, composition=None, production_process=None,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        boundary="A1", target_factor_unit="kgCO2e/t",
    )
    source = SourceRecord(
        source_id="unknown-subject", source_type=FactorSourceType.EPD,
        provider="issuer", locator="evidence://unknown", material_name="alumina",
        factor_value=1.0, factor_unit="kgCO2e/t", factor_kind=FactorKind.EPD_INDICATOR,
        subject_type=FactorSubjectType.UNKNOWN,
        indicator="GWP-total", declared_product="alumina", boundary="A1", boundary_modules=("A1",),
    )

    result = qualify_record(activity, source)

    assert result.subject_type.status.value == "unknown"
    assert result.eligible is False
    assert result.primary_exclusion == "subject_type_mismatch"


def test_subject_type_is_validated_and_changes_request_fingerprint() -> None:
    raw = ResolutionRequest(material_name="alumina", quantity=1, subject_type="raw_material")
    product = ResolutionRequest(
        material_name="alumina", quantity=1, subject_type=FactorSubjectType.FINISHED_PRODUCT
    )

    assert raw.subject_type == FactorSubjectType.RAW_MATERIAL
    assert resolution_request_fingerprint(raw) != resolution_request_fingerprint(product)
    with pytest.raises(ValueError, match="supported FactorSubjectType"):
        ResolutionRequest(material_name="alumina", quantity=1, subject_type="not-a-subject")


def test_source_record_validates_subject_quality_and_admission_types() -> None:
    converted = SourceRecord(
        source_id="converted", source_type=FactorSourceType.EPD, provider="issuer",
        locator="evidence://converted", material_name="alumina", factor_value=1,
        factor_unit="kgCO2e/kg", factor_kind="epd_indicator",
        subject_type="raw_material", source_quality_status="verified", admission_eligible=True,
    )
    assert converted.factor_kind == FactorKind.EPD_INDICATOR
    assert converted.subject_type == FactorSubjectType.RAW_MATERIAL
    assert converted.source_quality_status == SourceQualityStatus.VERIFIED
    with pytest.raises(ValueError, match="subject_type"):
        replace(converted, subject_type="bad-subject")
    with pytest.raises(ValueError, match="source_quality_status"):
        replace(converted, source_quality_status="bad-quality")
    with pytest.raises(ValueError, match="admission_eligible"):
        replace(converted, admission_eligible=1)


@pytest.mark.asyncio
async def test_catalog_quality_fields_are_fail_closed_when_missing_or_invalid() -> None:
    digest = "4" * 64
    records = []
    for source_id, quality in (("missing-quality", None), ("invalid-quality", "UNREVIEWED")):
        item = {
            "record_id": source_id, "name": "steel coil", "primary_value": 1.0,
            "primary_unit": "kgCO2e/kg", "factor_kind": "lifecycle_factor",
            "indicator": "GWP-total", "declared_product": "steel coil",
            "boundary": "cradle-to-gate", "boundary_modules": ["A1", "A2", "A3"],
            "production_process": "electric arc furnace",
            "source_document_locator": "https://example.invalid/formal/steel",
            "source_document_sha256": "1" * 64,
        }
        if quality is not None:
            item["source_quality_status"] = quality
            item["admission_eligible"] = True
        records.append(item)
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: {
                "catalog_version": "fail-closed-quality/v1",
                "database": {"name": "catalog.db", "sha256": digest},
                "records": records,
            },
        )
    ).resolve(request())

    assert result.candidates == ()
    qualifications = result.trace.explain()["record_qualifications"]
    assert {item["source_quality"]["status"] for item in qualifications} == {
        "mismatch", "unknown"
    }
    assert {item["primary_exclusion"] for item in qualifications} == {
        "source_quality_not_admissible"
    }


def test_versioned_registry_resolves_mullite_spinel_process_and_relations():
    mullite = DEFAULT_MATERIAL_REGISTRY.resolve("电熔莫来石")
    assert mullite.identity.head_material == "mullite"
    assert mullite.identity.material_family == "mullite_products"
    assert mullite.identity.category == MaterialCategory.MANUFACTURED_MINERAL
    assert mullite.identity.manufacturing_route == ("electrofused",)
    assert mullite.material_rule_ids == ("material.mullite/v2",)
    assert mullite.process_rule_ids == ("process.electrofused/v2",)
    assert mullite.relation_ids == ("relation.mullite-is-aluminosilicate/v2",)

    spinel = DEFAULT_MATERIAL_REGISTRY.resolve("烧结尖晶石")
    assert spinel.identity.head_material == "spinel"
    assert spinel.identity.manufacturing_route == ("sintered",)


def test_entity_first_parser_assigns_roles_without_treating_type_or_form_as_entity():
    aluminium = DEFAULT_MATERIAL_REGISTRY.resolve("金属铝")
    assert aluminium.identity.base_entity_id == "mat.element.aluminium"
    assert aluminium.identity_resolution.outcome == IdentityOutcome.RESOLVED
    roles = {(span.text, span.role) for span in aluminium.mention.spans}
    assert ("金属", SemanticRole.ENTITY_TYPE) in roles
    assert ("铝", SemanticRole.BASE_ENTITY) in roles

    steel_fiber = DEFAULT_MATERIAL_REGISTRY.resolve("钢纤维")
    roles = {(span.text, span.role) for span in steel_fiber.mention.spans}
    assert ("钢", SemanticRole.BASE_ENTITY) in roles
    assert ("钢纤维", SemanticRole.PRODUCT_FORM) in roles
    assert steel_fiber.identity.base_entity_id == "mat.alloy.steel"

    generic_aluminium = DEFAULT_MATERIAL_REGISTRY.resolve("通用铝金属")
    assert generic_aluminium.identity.base_entity_id == "mat.element.aluminium"
    assert generic_aluminium.identity.product_entity_id is None
    assert generic_aluminium.identity_resolution.outcome == IdentityOutcome.RESOLVED

    magnesia = DEFAULT_MATERIAL_REGISTRY.resolve("95%高纯镁砂")
    assert magnesia.mention.purity == pytest.approx(95.0)
    assert magnesia.mention.grade_modifiers == ("高纯",)
    assert {span.role for span in magnesia.mention.spans} >= {
        SemanticRole.PURITY, SemanticRole.GRADE_MODIFIER, SemanticRole.BASE_ENTITY,
    }


def test_entity_first_parser_preserves_composite_constituents_and_context_exclusions():
    composite = DEFAULT_MATERIAL_REGISTRY.resolve("莫来石-碳化硅砖")
    assert composite.identity.entity_type.value == "COMPOSITE"
    assert set(composite.identity.constituent_entity_ids) == {
        "mat.mineral.mullite", "mat.compound.silicon_carbide",
    }
    assert composite.identity.product_form == "brick"

    zircon = DEFAULT_MATERIAL_REGISTRY.resolve("锆莫来石")
    assert set(zircon.identity.constituent_entity_ids) == {
        "mat.compound.zirconia", "mat.mineral.mullite",
    }

    ladle_component = DEFAULT_MATERIAL_REGISTRY.resolve("钢包用透气元件")
    assert ladle_component.identity_resolution.outcome == IdentityOutcome.UNKNOWN
    assert ladle_component.identity.base_entity_id is None


@pytest.mark.asyncio
async def test_semantic_index_does_not_recall_silicon_or_alumina_for_metallic_aluminium():
    silicon = record(
        "silicon", "金属硅粉", 13.1, product_form="powder",
        declared_product="金属硅粉", boundary_modules=("A1", "A2", "A3"),
    )
    alumina = record(
        "alumina", "氧化铝", 2.8,
        declared_product="氧化铝", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([silicon, alumina])
    ).resolve(ResolutionRequest(material_name="金属铝", quantity=1))

    assert result.status == ResolutionStatus.SUPPLIER_DATA_REQUIRED
    assert result.candidates == ()
    explanation = result.trace.explain()
    assert explanation["material_identity"]["base_entity_id"] == "mat.element.aluminium"
    assert explanation["local_retrieval"]["record_count"] == 0
    assert explanation["local_retrieval"]["semantic_index_anchor"]["registry_version"] == "material-semantic-registry/2.2.1"


@pytest.mark.asyncio
async def test_generic_aluminium_requires_route_choice_when_primary_and_secondary_both_exist():
    primary = record(
        "primary-al", "原铝", 10.0,
        declared_product="原铝", boundary_modules=("A1", "A2", "A3"),
    )
    secondary = record(
        "secondary-al", "再生铝", 1.0,
        declared_product="再生铝", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([primary, secondary])
    ).resolve(ResolutionRequest(material_name="金属铝", quantity=1))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.trace.explain()["required_choice"]["field"] == "route"
    assert set(result.trace.explain()["required_choice"]["options"]) == {
        "primary",
        "secondary",
        "unknown",
    }
    admissions = result.trace.explain()["candidate_admissions"]
    assert {item["source_id"] for item in admissions} == {"primary-al", "secondary-al"}
    assert all(item["retrieval_strategy"] == LinkStrategy.RELATED.value for item in admissions)
    assert all(item["admitted"] and not item["observation_only"] for item in admissions)
    assert all(item["identity_proof_ids"] for item in admissions)


@pytest.mark.asyncio
async def test_generic_aluminium_natural_word_order_requires_route_choice() -> None:
    records = (
        replace(record(
            "natural-primary-al", "原铝", 10.0,
            declared_product="原铝", boundary_modules=("A1", "A2", "A3"),
        ), subject_type=FactorSubjectType.RAW_MATERIAL),
        replace(record(
            "natural-secondary-al", "再生铝", 1.0,
            declared_product="再生铝", boundary_modules=("A1", "A2", "A3"),
        ), subject_type=FactorSubjectType.RAW_MATERIAL),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(records)
    ).resolve(ResolutionRequest(
        material_name="通用铝金属", quantity=1,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    choice = result.trace.explain()["required_choice"]
    assert choice["field"] == "route"
    assert set(choice["options"]) == {"primary", "secondary", "unknown"}


@pytest.mark.parametrize(
    ("name", "value", "entity_id", "basis"),
    (
        ("70烧结镁砂", 70.0, "mat.compound.magnesia", "component.MgO"),
        ("80烧结镁砂", 80.0, "mat.compound.magnesia", "component.MgO"),
        ("烧结镁砂90", 90.0, "mat.compound.magnesia", "component.MgO"),
        ("尖晶石90", 90.0, "mat.engineered.spinel", "component.Al2O3"),
        ("刚玉90", 90.0, "mat.mineral.corundum", "component.Al2O3"),
    ),
)
def test_entity_scoped_numeric_grade_defaults_without_user_question(name, value, entity_id, basis):
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve(name)
    grade = resolved.mention.numeric_grade

    assert resolved.identity.base_entity_id == entity_id
    assert grade is not None
    assert grade.grade_value == value
    assert grade.basis_component_id == basis
    assert grade.evidence_scope.value == "ORGANIZATION_BUSINESS_RULE"
    assert grade.specification_operator is None
    assert "numeric_grade_basis" not in resolved.identity.unresolved_attributes


def test_explicit_chemistry_overrides_name_grade_and_preserves_operator():
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve("烧结镁砂90", composition="MgO ≥ 95%")
    grade = resolved.mention.numeric_grade

    assert grade is not None
    assert grade.grade_value == pytest.approx(95.0)
    assert grade.basis_component_id == "component.MgO"
    assert grade.interpretation_kind.value == "EXPLICIT_COMPOSITION"
    assert grade.specification_operator.value == "MINIMUM"
    assert grade.specification_min == pytest.approx(95.0)


def test_explicit_formula_value_without_percent_is_not_an_implicit_grade_class():
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve("烧结镁砂", composition="MgO 90")
    grade = resolved.mention.numeric_grade

    assert grade is not None
    assert grade.grade_value == pytest.approx(90.0)
    assert grade.basis_component_id == "component.MgO"
    assert grade.interpretation_kind.value == "EXPLICIT_COMPOSITION"
    assert grade.evidence_scope.value == "EXPLICIT_TEXT"
    assert grade.specification_operator.value == "NOMINAL"


@pytest.mark.parametrize(
    ("name", "role"),
    (
        ("F80碳化硅", NumericTokenRole.GRIT_SIZE),
        ("P80白刚玉", NumericTokenRole.GRIT_SIZE),
        ("T60板状刚玉", NumericTokenRole.MODEL_CODE),
        ("CT800氧化铝", NumericTokenRole.MODEL_CODE),
        ("AISI 446钢纤维", NumericTokenRole.ALLOY_GRADE),
        ("6061铝合金", NumericTokenRole.ALLOY_GRADE),
    ),
)
def test_numeric_negative_contexts_are_not_promoted_to_purity(name, role):
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve(name)

    assert resolved.mention.numeric_grade is None
    assert any(token.role == role for token in resolved.mention.numeric_tokens)
    assert all(token.role != NumericTokenRole.PURITY_GRADE for token in resolved.mention.numeric_tokens)


def test_grade_and_particle_size_are_classified_independently():
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve("90烧结镁砂 0-3mm")
    roles = {token.role for token in resolved.mention.numeric_tokens}

    assert resolved.mention.numeric_grade.grade_value == pytest.approx(90.0)
    assert NumericTokenRole.PURITY_GRADE in roles
    assert NumericTokenRole.PARTICLE_SIZE in roles


def test_source_record_uses_the_same_numeric_grade_schema_as_the_request():
    enriched = DEFAULT_MATERIAL_REGISTRY.enrich_source(record(
        "source-magnesia-90", "90烧结镁砂", 1.0,
        declared_product="90烧结镁砂", boundary_modules=("A1", "A2", "A3"),
    ))

    assert enriched.metadata["grade"] == "90"
    assert enriched.metadata["grade_schema_id"] == (
        "grade.magnesia.mgo.organization-default/v1"
    )
    assert enriched.metadata["grade_basis_component_id"] == "component.MgO"


def test_multiple_grade_like_tokens_require_resolution_instead_of_picking_one():
    resolved = DEFAULT_MATERIAL_REGISTRY.resolve("70烧结镁砂90")

    assert resolved.mention.numeric_grade is None
    assert sum(
        token.role == NumericTokenRole.UNRESOLVED
        for token in resolved.mention.numeric_tokens
    ) == 2
    assert "numeric_grade_basis" in resolved.identity.unresolved_attributes


@pytest.mark.asyncio
async def test_grit_qualifier_cannot_be_erased_by_a_generic_material_alias():
    generic = record(
        "generic-sic", "碳化硅", 2.0,
        declared_product="碳化硅", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([generic])
    ).resolve(ResolutionRequest(material_name="F80碳化硅", quantity=1))

    assert result.reviewable_candidates
    assert result.reviewable_candidates[0].resolution_type not in {
        ResolutionType.DIRECT_EXACT,
        ResolutionType.DIRECT_ALIAS,
        ResolutionType.UNIT_CONVERTED,
    }
    admission = result.trace.explain()["candidate_admissions"][0]
    assert admission["retrieval_strategy"] == LinkStrategy.RELATED.value


@pytest.mark.asyncio
async def test_same_entity_numeric_grade_difference_becomes_grade_gap_not_silent_match():
    source = record(
        "magnesia-80", "80烧结镁砂", 1.0,
        product_form=None, composition=None, production_process="sintered",
        declared_product="80烧结镁砂", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    ).resolve(ResolutionRequest(material_name="90烧结镁砂", quantity=1, geography="CN", year=2024))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.trace.explain()["request_gaps"] == ()
    assert result.reviewable_candidates == ()
    assert result.diagnostic_candidates[0].resolution_type == ResolutionType.GRADE_PROXY
    assert "GRADE_SPECIFICATION_CONFLICT" in result.reason_codes
    grade_gaps = tuple(
        gap
        for candidate in result.trace.explain()["candidate_gaps"]
        for gap in candidate["gaps"]
        if gap["gap_type"] == GapType.GRADE_COMPOSITION.value
    )
    assert grade_gaps
    assert any("90" in str(gap["target_value"]) and "80" in str(gap["candidate_value"]) for gap in grade_gaps)


@pytest.mark.asyncio
async def test_same_entity_same_grade_exact_source_remains_direct():
    source = record(
        "magnesia-90-exact", "90烧结镁砂", 1.0,
        product_form=None, composition=None, production_process="sintered",
        declared_product="90烧结镁砂", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    ).resolve(ResolutionRequest(material_name="90烧结镁砂", quantity=1))

    assert result.candidates[0].resolution_type == ResolutionType.DIRECT_EXACT
    assert not any(
        gap["gap_type"] == GapType.GRADE_COMPOSITION.value
        for candidate in result.trace.explain()["candidate_gaps"]
        for gap in candidate["gaps"]
    )


@pytest.mark.asyncio
async def test_explicit_composition_produces_one_structured_grade_gap_only():
    source = record(
        "magnesia-80-explicit", "80烧结镁砂", 1.0,
        production_process="sintered", declared_product="80烧结镁砂",
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    ).resolve(ResolutionRequest(
        material_name="烧结镁砂", composition="MgO ≥ 95%", quantity=1,
    ))

    grade_gaps = tuple(
        gap
        for candidate in result.trace.explain()["candidate_gaps"]
        for gap in candidate["gaps"]
        if gap["gap_type"] == GapType.GRADE_COMPOSITION.value
    )
    assert len(grade_gaps) == 1
    assert "95" in str(grade_gaps[0]["target_value"])


@pytest.mark.asyncio
async def test_numeric_grade_is_part_of_normalized_business_fingerprint():
    engine = A1FactorResolutionEngine()
    grade_70 = await engine.resolve(ResolutionRequest(
        request_id="grade-fingerprint-70", material_name="70烧结镁砂", quantity=1,
    ))
    grade_90 = await engine.resolve(ResolutionRequest(
        request_id="grade-fingerprint-90", material_name="90烧结镁砂", quantity=1,
    ))

    assert (
        grade_70.trace.normalized_business_fingerprint
        != grade_90.trace.normalized_business_fingerprint
    )


@pytest.mark.asyncio
async def test_unbound_composite_grade_is_the_exception_that_requests_basis():
    result = await A1FactorResolutionEngine().resolve(
        ResolutionRequest(material_name="莫来石-碳化硅砖90", quantity=1)
    )

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.trace.explain()["required_choice"]["field"] == "numeric_grade_basis"


def test_draft_registry_rule_cannot_affect_runtime_resolution():
    registry = VersionedMaterialSemanticRegistry(
        version="test-registry/draft-only",
        material_rules=(MaterialRule(
            "material.mullite/draft",
            "mullite",
            "mullite_products",
            MaterialCategory.MANUFACTURED_MINERAL,
            ("莫来石",),
            status=RegistryRuleStatus.DRAFT,
        ),),
        process_rules=(),
        form_rules=(),
    )
    result = registry.resolve("莫来石")
    assert result.identity.category == MaterialCategory.UNKNOWN
    assert result.material_rule_ids == ()


@pytest.mark.asyncio
async def test_mullite_related_recall_is_material_aware_not_process_name_overlap():
    sintered_mullite = record(
        "mullite-sintered", "烧结莫来石", 2.1,
        product_form=None, composition=None, production_process=None,
        declared_product="烧结莫来石", boundary_modules=("A1", "A2", "A3"),
    )
    fused_corundum = record(
        "corundum-fused", "电熔刚玉", 3.3,
        product_form=None, composition=None, production_process=None,
        declared_product="电熔刚玉", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered_mullite, fused_corundum])
    ).resolve(ResolutionRequest(
        material_name="电熔莫来石", quantity=1, geography="CN", year=2024,
    ))
    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any(
        item["source_id"] == "mullite-sintered"
        for item in result.trace.explain()["excluded_candidates"]
    )
    retrieved = result.trace.explain()["local_retrieval"]["records"]
    assert {item["source_id"] for item in retrieved} == {"mullite-sintered"}


@pytest.mark.asyncio
async def test_unknown_material_suggestion_remains_draft_and_trace_visible():
    class SuggestionPort:
        async def suggest(self, normalized_name):
            return RegistryRuleSuggestion(
                suggestion_id="suggestion:new-material:1",
                normalized_name=normalized_name,
                proposed_head_material="new_material",
                proposed_material_family="candidate_family",
                rationale="LLM proposal constrained to semantic fields; no factor value",
                confidence=0.62,
            )

    result = await A1FactorResolutionEngine(rule_suggestions=SuggestionPort()).resolve(
        ResolutionRequest(material_name="全新材料X", quantity=1)
    )
    semantic = result.trace.explain()["semantic_registry"]
    assert semantic["sufficiently_identified"] is False
    assert semantic["draft_suggestion"]["status"] == "draft"
    assert semantic["suggestion_requires_human_review"] is True
    assert result.trace.explain()["material_identity"]["category"] == "UNKNOWN"


def record(source_id: str, name: str, value: float, unit: str = "kgCO2e/kg", **kwargs) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=kwargs.pop("source_type", FactorSourceType.EPD),
        provider=kwargs.pop("provider", "test registry"),
        locator=kwargs.pop("locator", f"https://test/{source_id}"),
        material_name=name,
        factor_value=value,
        factor_unit=unit,
        geography=kwargs.pop("geography", "CN"),
        year=kwargs.pop("year", 2024),
        product_form=kwargs.pop("product_form", "coil"),
        composition=kwargs.pop("composition", "carbon steel"),
        production_process=kwargs.pop("production_process", "electric arc furnace"),
        boundary=kwargs.pop("boundary", "cradle-to-gate"),
        citation=kwargs.pop("citation", ""),
        excerpt=kwargs.pop("excerpt", ""),
        factor_kind=kwargs.pop("factor_kind", FactorKind.LIFECYCLE_FACTOR),
        indicator=kwargs.pop("indicator", "GWP-total"),
        declared_product=kwargs.pop("declared_product", name),
        boundary_modules=kwargs.pop("boundary_modules", ()),
        metadata=kwargs.pop("metadata", kwargs),
    )


def request(**changes) -> ResolutionRequest:
    values = {
        "material_name": "steel coil",
        "quantity": 1,
        "quantity_unit": "t",
        "geography": "CN",
        "year": 2024,
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "boundary": "cradle-to-gate",
    }
    values.update(changes)
    if "target_factor_unit" not in changes and values["quantity_unit"] in {"kg", "t"}:
        values["target_factor_unit"] = "kgCO2e/kg"
    return ResolutionRequest(**values)


def parameter(parameter_id: str, name: str, value: float, unit: str, **metadata) -> ParameterEvidence:
    return ParameterEvidence(
        parameter_id=parameter_id,
        name=name,
        value=value,
        unit=unit,
        source_type=ParameterSourceType.FORMAL_STANDARD,
        provider="test engineering memo",
        locator=f"https://test/parameter/{parameter_id}",
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_local_success_bypasses_proxy():
    local = record("local-1", "steel coil", 1.85, source_type=FactorSourceType.LOCAL_DATABASE)

    class ExplodingProxy:
        async def search(self, activity, material_class):
            raise AssertionError("proxy should not run when local retrieval is sufficient")

    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([local]),
        proxy_retrieval=ExplodingProxy(),
    )
    result = await engine.resolve(request())
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].origin == CandidateOrigin.LOCAL

@pytest.mark.asyncio
async def test_proxy_success_is_technology_aware_and_material_class_is_late():
    proxy = record(
        "proxy-1", "recycled steel billet", 0.7,
        product_form="coil", composition="carbon steel",
        production_process="electric arc furnace", metadata={"material_class": "steel", "family": "metals"},
    )
    engine = A1FactorResolutionEngine(
        proxy_retrieval=InMemoryProxyRepository([proxy]),
    )
    result = await engine.resolve(request(material_name="unlisted steel alloy", composition="carbon steel"))
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].origin == CandidateOrigin.PROXY
    assert result.candidates[0].proxy_class is not None
    assert "proxy value" in result.candidates[0].limitations[0]


@pytest.mark.asyncio
async def test_unresolved_returns_supplier_follow_up_without_retry_loop():
    engine = A1FactorResolutionEngine()
    result = await engine.resolve(request(material_name="unknown composite"))
    assert result.status == ResolutionStatus.SUPPLIER_DATA_REQUIRED
    assert result.follow_up is not None and result.follow_up.value == "supplier-data"
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_process_conflict_becomes_gap_and_unadjusted_reference_candidate():
    incompatible = record(
        "bad-process", "steel coil", 1.1,
        production_process="basic oxygen furnace",
    )
    compatible = record(
        "good-process", "steel coil", 1.2,
        geography=None, year=None, product_form=None, composition=None,
        production_process="electric arc furnace", boundary=None,
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([incompatible, compatible]),
    )
    result = await engine.resolve(request(top_k=2))
    assert result.status == ResolutionStatus.REFERENCE_REVIEW_REQUIRED
    assert result.candidates == ()
    assert [c.source.source_id for c in result.reviewable_candidates] == ["good-process"]
    assert [c.source.source_id for c in result.diagnostic_candidates] == ["bad-process"]
    assert result.missing_gaps == ()
    assert result.questions == ()
    assert any(
        item["source_id"] == "bad-process"
        and "unresolved_process_variant_requires_process_model" in item["reasons"]
        for item in result.trace.explain()["excluded_candidates"]
    )
    blocked_id = next(
        item["candidate_id"]
        for item in result.trace.explain()["excluded_candidates"]
        if item["source_id"] == "bad-process"
    )
    with pytest.raises(KeyError, match="candidate not found"):
        await engine.approve(
            result.request_id,
            blocked_id,
            "reviewer",
            "must not override process model",
            ApprovalMode.REFERENCE_OVERRIDE,
        )


def test_deterministic_unit_conversion():
    assert convert_mass(1, "t", "kg") == 1000
    assert convert_factor(1000, "kgCO2e/t", "kgCO2e/kg") == 1
    assert convert_factor(1000, "gCO2e/kg", "kgCO2e/kg") == 1


def test_blank_process_emission_is_missing_but_numeric_zero_is_explicit():
    assert explicit_process_emission_observation(None) is None
    assert explicit_process_emission_observation(0.0) == 0.0


def test_enterprise_blank_zero_policy_is_overridden_by_process_trigger():
    ordinary = interpret_process_emission_observation(None, blank_means_zero=True)
    assert ordinary is not None
    assert ordinary.value_kgco2e_per_t == 0
    assert ordinary.evidence_kind == "DATASET_DEFAULT_ZERO"
    assert ordinary.requires_calculation is False

    electrode = interpret_process_emission_observation(
        0.0, remark="电极9kg", blank_means_zero=True
    )
    assert electrode is not None
    assert electrode.requires_calculation is True
    assert electrode.evidence_kind == "TRIGGER_CONFLICT_REQUIRES_CALCULATION"


def test_stoichiometric_carbon_and_a1_a3_roles_are_deterministic():
    assert stoichiometric_carbon_emission_kgco2e_per_kg(9, 1, 1) == pytest.approx(0.033)
    standalone = resolve_accounting_assignment("焦炭")
    assert standalone.role == AccountingRole.REDUCTANT
    assert standalone.modules == (AccountingModule.A1_UPSTREAM_INPUT,)
    assignments = resolve_process_accounting_assignments(
        "电熔尖晶石",
        (parameter(
            "electrode-process",
            "target_additional_process_emission_kgco2e_per_kg",
            0.033,
            "kgCO2e/kg",
            process_emission_kind="direct_electrode_oxidation_co2",
        ),),
    )
    assert [(item.subject, item.role, item.modules) for item in assignments] == [
        ("电熔尖晶石", AccountingRole.TARGET_PRODUCT, ()),
        ("电极", AccountingRole.CONSUMABLE_ELECTRODE,
         (AccountingModule.A1_UPSTREAM_INPUT,)),
        ("电极现场氧化/反应", AccountingRole.DIRECT_PROCESS_EMISSION,
         (AccountingModule.A3_DIRECT_PROCESS,)),
    ]
    electrode_a1 = assignments[1]
    direct_a3 = assignments[2]
    assert electrode_a1.quantification_status == (
        AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
    )
    assert electrode_a1.missing_inputs == (
        "consumable_quantity_kg_per_t",
        "consumable_upstream_factor_kgco2e_per_kg",
    )
    assert direct_a3.quantification_status == AccountingQuantificationStatus.QUANTIFIED
    assert direct_a3.missing_inputs == ()
    unrelated = resolve_process_accounting_assignments(
        "电熔尖晶石",
        (parameter(
            "unrelated-provider-text", "target_total_energy_kgce_per_t", 185,
            "kgce/t", unrelated_note="electrode vendor appears only in free text",
        ),),
    )
    assert [(item.subject, item.role) for item in unrelated] == [
        ("电熔尖晶石", AccountingRole.TARGET_PRODUCT)
    ]


@pytest.mark.parametrize("chemical_name", ["氧化铝", "氧化镁", "二氧化硅"])
def test_chemical_names_never_trigger_direct_a3_without_explicit_context(chemical_name):
    assignment = resolve_accounting_assignment(chemical_name, quantified=True)

    assert assignment.role == AccountingRole.PURCHASED_RAW_MATERIAL
    assert assignment.modules == (AccountingModule.A1_UPSTREAM_INPUT,)
    assert assignment.quantification_status == AccountingQuantificationStatus.QUANTIFIED


def test_explicit_process_context_can_trigger_direct_a3():
    assignment = resolve_accounting_assignment(
        "碳",
        use_context="制造现场氧化过程排放",
    )

    assert assignment.role == AccountingRole.DIRECT_PROCESS_EMISSION
    assert assignment.modules == (AccountingModule.A3_DIRECT_PROCESS,)
    assert assignment.quantification_status == (
        AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
    )
    assert assignment.missing_inputs == ("emission_factor",)


@pytest.mark.asyncio
async def test_standalone_coke_factor_is_reported_as_a1_upstream_input():
    coke = record("coke-factor", "焦炭", 2.5)
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([coke])
    ).resolve(ResolutionRequest(material_name="焦炭", quantity=1))

    assert result.accounting_assignments[0].role == AccountingRole.REDUCTANT
    assert result.accounting_assignments[0].modules == (
        AccountingModule.A1_UPSTREAM_INPUT,
    )


def test_provenance_invariant():
    source = record("s1", "steel coil", 1.0)
    with pytest.raises(ValueError):
        from a1_factor_engine.models import Candidate, CandidateOrigin

        Candidate(
            candidate_id="bad", origin=CandidateOrigin.LOCAL, source=source,
            provenance=source.provenance.__class__(
                source_id="other", source_type=source.source_type, provider="x", locator="https://x"
            ), factor_value=1, factor_unit="kgCO2e/kg", score=1,
            reasons=(), limitations=(), dimensions={},
        )


@pytest.mark.asyncio
async def test_approval_rejection_and_immutable_locking():
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([record("s1", "steel coil", 1.0)]))
    req = request()
    result = await engine.resolve(req)
    candidate_id = result.candidates[0].candidate_id
    with pytest.raises(ValueError):
        await engine.lock(req.request_id, candidate_id, "alice")
    await engine.approve(req.request_id, candidate_id, "alice")
    locked = await engine.lock(req.request_id, candidate_id, "alice")
    assert locked.candidate.candidate_id == candidate_id
    trace = await engine.trace(req.request_id)
    assert trace is not None and trace.latest("lock") is not None
    assert trace.latest("lock").details["trace_remains_appendable"] is True
    assert await engine.lock(req.request_id, candidate_id, "bob") == locked
    with pytest.raises(ValueError):
        await engine.lock(req.request_id, "local:other", "alice")


@pytest.mark.asyncio
async def test_lock_rejects_factor_total_inconsistency():
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record("lock-total", "steel coil", 1.0)])
    )
    req = request(request_id="lock-total-invariant")
    result = await engine.resolve(req)
    candidate = result.candidates[0]
    await engine.approve(req.request_id, candidate.candidate_id, "reviewer")
    tampered = replace(candidate, total_emissions_kgco2e=999.0)
    engine.store.recommendations[req.request_id] = replace(
        result, candidates=(tampered,)
    )

    with pytest.raises(ValueError, match="total emissions are inconsistent"):
        await engine.lock(req.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_approval_and_lock_recheck_hard_process_gate_after_store_tampering():
    source = record("hard-gate-defense", "steel coil", 1.0)

    approve_engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    )
    approve_result = await approve_engine.resolve(request(request_id="hard-gate-approve"))
    hard_candidate = replace(
        approve_result.candidates[0],
        resolution_type=ResolutionType.UNADJUSTED_PROCESS_PROXY,
        result_tier=ResultTier.REFERENCE_ONLY,
    )
    approve_engine.store.recommendations[approve_result.request_id] = replace(
        approve_result,
        status=ResolutionStatus.REFERENCE_REVIEW_REQUIRED,
        candidates=(hard_candidate,),
    )
    with pytest.raises(ValueError, match="hard-blocked and cannot be approved"):
        await approve_engine.approve(
            approve_result.request_id,
            hard_candidate.candidate_id,
            "reviewer",
            "tampered diagnostic candidate",
            ApprovalMode.REFERENCE_OVERRIDE,
        )

    lock_engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    )
    lock_result = await lock_engine.resolve(request(request_id="hard-gate-lock"))
    candidate = lock_result.candidates[0]
    await lock_engine.approve(lock_result.request_id, candidate.candidate_id, "reviewer")
    lock_engine.store.recommendations[lock_result.request_id] = replace(
        lock_result,
        candidates=(replace(
            candidate,
            resolution_type=ResolutionType.UNADJUSTED_PROCESS_PROXY,
        ),),
    )
    with pytest.raises(ValueError, match="hard-blocked and cannot be locked"):
        await lock_engine.lock(lock_result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_trace_explains_local_hits_proxy_route_exclusions_and_ranking():
    local_conflict = record(
        "local-conflict", "unlisted steel alloy", 1.1,
        production_process="basic oxygen furnace",
        source_type=FactorSourceType.LOCAL_DATABASE,
    )
    proxy = record(
        "proxy-good", "recycled steel billet", 0.8,
        product_form="coil", composition="carbon steel",
        production_process="electric arc furnace",
        metadata={"material_class": "unlisted steel alloy", "family": "metals"},
    )
    anchor = DatabaseVersionAnchor(
        "emission_factors.db", "factor-catalog-v0.2.1", "a" * 64, "http://127.0.0.1:5004/api/v2/factors/catalog"
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([local_conflict], anchor=anchor),
        proxy_retrieval=InMemoryProxyRepository([proxy]),
    )
    req = request(material_name="unlisted steel alloy")
    result = await engine.resolve(req)
    trace = await engine.trace(req.request_id)

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert trace is result.trace
    assert trace is not None and trace.database_anchor is not None
    assert trace.database_anchor.identity == anchor.identity
    assert trace.database_anchor.content_sha256 is not None
    assert trace.latest("local_retrieval").details["records"][0]["source_id"] == "local-conflict"
    assert trace.latest("local_evaluate").details["decision"] == "resolve_local_gaps"
    assert trace.latest("process_variant_resolution").details["modes"][0]["mode"] == "UNADJUSTED_PROCESS_PROXY"
    ranking = trace.latest("rank").details["ranking"]
    assert {item["source_id"] for item in ranking} == {"local-conflict"}
    explanation = trace.explain()
    assert explanation["database_version"]["database_sha256"] == "a" * 64
    assert explanation["proxy_decision"]["decision"] == "resolve_local_gaps"
    assert any(
        gap["gap_type"] == GapType.PROCESS_VARIANT.value
        for gap in explanation["candidate_gaps"][0]["gaps"]
    )
    assert explanation["final_ranking"] == ranking
    assert trace.to_dict()["entries"][-1]["stage"] == "top_k"
    assert json.loads(json.dumps(trace.to_dict()))["trace_revision"] == trace.revision


@pytest.mark.asyncio
async def test_same_request_comparison_explains_database_update():
    old_anchor = DatabaseVersionAnchor("emission_factors.db", "v1", "1" * 64, "http://catalog")
    new_anchor = DatabaseVersionAnchor("emission_factors.db", "v2", "2" * 64, "http://catalog")
    repository = InMemoryFactorRepository([record("steel-v1", "steel coil", 1.0)], anchor=old_anchor)
    engine = A1FactorResolutionEngine(local_retrieval=repository)

    before = await engine.resolve(request())
    repository.records = [record("steel-v2", "steel coil", 0.8)]
    repository.anchor = new_anchor
    repository.__post_init__()
    after = await engine.resolve(request())
    comparison = await engine.compare_traces(before.request_id, after.request_id)

    assert comparison["same_request"] is True
    assert comparison["database_changed"] is True
    assert comparison["local_hits_removed"] == ("steel-v1",)
    assert comparison["local_hits_added"] == ("steel-v2",)
    assert "formal factor database anchor changed" in comparison["explanations"]
    assert comparison["ranking_before"] != comparison["ranking_after"]


@pytest.mark.asyncio
async def test_http_catalog_adapter_anchors_formal_database_response():
    digest = "7" * 64
    payload = {
        "catalog_version": "factor-catalog-v0.2.1",
        "database": {"name": "emission_factors.db", "sha256": digest},
        "records": [{
                "record_id": "lifecycle_factor:steel",
                "source_quality_status": "VERIFIED",
                "admission_eligible": True,
                "subject_type": "raw_material",
            "category": "lifecycle_factor",
            "code": "STEEL_COIL",
            "name": "steel coil",
            "primary_value": 1.25,
            "primary_unit": "kgCO2e/kg",
            "source": "formal test source",
            "source_id": "FORMAL_SOURCE",
            "document_status": "PUBLISHED",
            "aliases": [],
            "boundary": "cradle-to-gate",
            "indicator": "GWP-total",
            "declared_product": "steel coil",
            "product_form": "coil",
            "composition": "carbon steel",
            "production_process": "electric arc furnace",
            "source_document_locator": "https://example.invalid/formal/steel-coil",
            "source_document_sha256": "5" * 64,
        }],
    }
    adapter = HttpCatalogFactorRepository(
        expected_sha256=digest,
        fetch_json=lambda _: payload,
    )
    engine = A1FactorResolutionEngine(local_retrieval=adapter)
    req = request()
    result = await engine.resolve(req)

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.trace is not None
    assert result.trace.database_anchor.database_sha256 == digest
    assert result.candidates[0].source.metadata["catalog_version"] == "factor-catalog-v0.2.1"


@pytest.mark.asyncio
async def test_exact_and_registered_synonym_are_merged_before_ranking():
    exact = record("exact", "steel coil", 1.0, source_type=FactorSourceType.LOCAL_DATABASE)
    synonym = record(
        "synonym", "hot rolled steel", 1.1,
        source_type=FactorSourceType.LOCAL_DATABASE,
        metadata={"aliases": '["steel coil"]'},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([synonym, exact])
    ).resolve(request())

    attempts = result.trace.explain()["link_attempts"]
    assert [candidate.source.source_id for candidate in result.candidates] == ["exact", "synonym"]
    assert attempts[0]["strategy"] == LinkStrategy.EXACT.value
    assert attempts[0]["outcome"] == LinkOutcome.MATCHED.value
    assert attempts[1]["strategy"] == LinkStrategy.SYNONYM.value
    assert attempts[1]["outcome"] == LinkOutcome.MATCHED.value
    assert "alias resolved" in attempts[1]["reason"]


@pytest.mark.asyncio
async def test_synonym_link_requires_declared_alias_not_substring_similarity():
    undeclared = record("substring", "steel coil", 1.0, source_type=FactorSourceType.LOCAL_DATABASE)
    alias = record(
        "alias", "rolled steel product", 1.1,
        source_type=FactorSourceType.LOCAL_DATABASE,
        metadata={"aliases": '["premium steel coil"]'},
    )
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([undeclared, alias]))
    result = await engine.resolve(request(material_name="premium steel coil"))

    assert [candidate.source.source_id for candidate in result.candidates] == ["alias"]
    attempts = result.trace.latest("local_retrieval").details["link_attempts"]
    assert attempts[0]["outcome"] == LinkOutcome.NO_MATCH.value
    assert attempts[1]["candidate_source_ids"] == ("alias",)


@pytest.mark.asyncio
async def test_related_recall_never_masquerades_as_direct_exact():
    related = record("related", "steel coil", 1.0, source_type=FactorSourceType.LOCAL_DATABASE)
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([related]),
    ).resolve(request(material_name="premium steel coil"))

    candidate = result.reviewable_candidates[0]
    assert candidate.resolution_type == ResolutionType.CLASS_GENERIC_PROXY
    assert candidate.result_tier == ResultTier.REFERENCE_ONLY
    assert any(gap.gap_type == GapType.MATERIAL_ABSENT for gap in candidate.gaps)
    attempts = result.trace.latest("local_retrieval").details["link_attempts"]
    assert attempts[-1]["strategy"] == LinkStrategy.RELATED.value


@pytest.mark.asyncio
async def test_normalization_rules_linking_ledger_and_confidence_are_observable():
    complete = record("complete", "steel coil", 1.0, source_type=FactorSourceType.LOCAL_DATABASE)
    sparse = record(
        "sparse", "steel coil", 1.1,
        source_type=FactorSourceType.LOCAL_DATABASE,
        geography=None, year=None, product_form=None, composition=None,
        production_process=None, boundary=None,
    )
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([sparse, complete]))
    first = await engine.resolve(request(material_name="ＳＴＥＥＬ-ＣＯＩＬ"))
    second = await engine.resolve(request(material_name="ＳＴＥＥＬ-ＣＯＩＬ"))

    normalized = first.trace.latest("normalize").details
    assert "text.unicode_nfkc/v1" in normalized["normalization_rule_ids"]
    assert "text.separator_space/v1" in normalized["normalization_rule_ids"]
    assert first.candidates[0].source.source_id == "complete"
    assert first.candidates[0].evidence_coverage == 1.0
    assert first.confidence is not None
    assert first.confidence == second.confidence
    assert first.trace.explain()["confidence"]["value"] == first.confidence.value


@pytest.mark.asyncio
async def test_all_linking_strategies_end_in_explicit_unresolved_attempt():
    result = await A1FactorResolutionEngine().resolve(request(material_name="unknown composite"))
    attempts = result.trace.explain()["link_attempts"]

    assert [attempt["strategy"] for attempt in attempts] == [
        LinkStrategy.EXACT.value,
        LinkStrategy.SYNONYM.value,
        LinkStrategy.RELATED.value,
        LinkStrategy.CLASS_AWARE_PROXY.value,
        LinkStrategy.UNRESOLVED.value,
    ]
    assert attempts[-1]["outcome"] == LinkOutcome.NO_MATCH.value


@pytest.mark.asyncio
async def test_reference_flow_uses_each_sourced_mass_scenario_without_averaging():
    factor = record("brick-factor", "refractory brick", 1.5, product_form="brick")
    flows = [
        ReferenceFlowRecord(
            "measured", "refractory brick", "piece", 4.2,
            parameter("mass-measured", "mass_per_piece", 4.2, "kg/piece"),
        ),
        ReferenceFlowRecord(
            "spec", "refractory brick", "piece", 4.3,
            parameter("mass-spec", "mass_per_piece", 4.3, "kg/piece"),
        ),
    ]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([factor]),
        reference_flows=InMemoryReferenceFlowRepository(flows),
    ).resolve(request(
        material_name="refractory brick", quantity=100, quantity_unit="piece",
        product_form="brick",
    ))

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert [candidate.resolved_quantity_kg for candidate in result.candidates] == [420.0, 430.0]
    assert [candidate.total_emissions_kgco2e for candidate in result.candidates] == [630.0, 645.0]
    assert all(candidate.resolution_type == ResolutionType.REFERENCE_FLOW_CONVERTED for candidate in result.candidates)
    assert {candidate.parameter_evidence_ids[0] for candidate in result.candidates} == {"mass-measured", "mass-spec"}


@pytest.mark.asyncio
async def test_reference_flow_without_mass_evidence_requests_only_required_input():
    factor = record("brick-factor", "refractory brick", 1.5, product_form="brick")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([factor]),
    ).resolve(request(
        material_name="refractory brick", quantity=100, quantity_unit="piece",
        product_form="brick",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.follow_up.value == "more-input"
    assert result.candidates == ()
    assert result.trace.explain()["required_fields"] == ("mass_per_piece", "dimensions+density")


@pytest.mark.asyncio
async def test_process_router_rebuilds_electrofused_mullite_from_sintered_factor():
    sintered = record(
        "sintered-mullite", "sintered mullite", 3.431355,
        product_form="grain", composition="mullite",
        production_process="sintered", boundary="cradle-to-gate",
        metadata={"includes_process": "true"},
    )
    values = (
        ("ref-energy", "reference_total_energy_kgce_per_t", 365, "kgce/t"),
        ("ref-elec-share", "reference_electricity_share", 0.76, "fraction"),
        ("ref-gas-share", "reference_natural_gas_share", 0.24, "fraction"),
        ("target-energy", "target_total_energy_kgce_per_t", 165, "kgce/t"),
        ("target-elec-share", "target_electricity_share", 1.0, "fraction"),
        ("elec-coef", "electricity_kgce_per_kwh", 0.1229, "kgce/kWh"),
        ("gas-coef", "natural_gas_kgce_per_nm3", 1.2143, "kgce/Nm3"),
        ("elec-ef", "electricity_ef_kgco2e_per_kwh", 0.5777, "kgCO2e/kWh"),
        ("gas-ef", "natural_gas_ef_kgco2e_per_nm3", 2.792671012566, "kgCO2e/Nm3"),
    )
    evidence = [parameter(
        *item,
        reference_source_id="sintered-mullite",
        target_material="electrofused mullite",
        target_process="electrofused",
    ) for item in values]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=InMemoryProcessParameterRepository(evidence),
    ).resolve(request(
        material_name="electrofused mullite", product_form="grain",
        composition="mullite", production_process="electrofused",
    ))

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.PROCESS_ADJUSTED
    assert candidate.factor_value == pytest.approx(2.701546778, abs=1e-9)
    assert any(step.formula_id == "process.replace_energy_components/v1" for step in candidate.transformation_steps)
    assert len(candidate.parameter_evidence_ids) == 9
    assert len(candidate.assumptions) == 5
    process_steps = [
        step for step in result.trace.explain()["transformation_steps"]
        if step["formula_id"] == "process.replace_energy_components/v1"
    ]
    assert process_steps[0]["output_value"] == pytest.approx(2.701546778)


@pytest.mark.asyncio
async def test_process_router_calculates_electrode_co2_from_closed_stoichiometry():
    sintered = record(
        "stoich-sintered-mullite", "sintered mullite", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        boundary="cradle-to-gate", metadata={"includes_process": "true"},
    )
    values = (
        ("ref-energy", "reference_total_energy_kgce_per_t", 365, "kgce/t"),
        ("ref-elec-share", "reference_electricity_share", 0.76, "fraction"),
        ("ref-gas-share", "reference_natural_gas_share", 0.24, "fraction"),
        ("target-energy", "target_total_energy_kgce_per_t", 165, "kgce/t"),
        ("target-elec-share", "target_electricity_share", 1.0, "fraction"),
        ("elec-coef", "electricity_kgce_per_kwh", 0.1229, "kgce/kWh"),
        ("gas-coef", "natural_gas_kgce_per_nm3", 1.2143, "kgce/Nm3"),
        ("elec-ef", "electricity_ef_kgco2e_per_kwh", 0.5777, "kgCO2e/kWh"),
        ("gas-ef", "natural_gas_ef_kgco2e_per_nm3", 2.792671012566, "kgCO2e/Nm3"),
        ("ref-process-zero", "reference_additional_process_emission_kgco2e_per_kg", 0, "kgCO2e/kg"),
        ("target-electrode-mass", "target_carbonaceous_consumable_kg_per_t", 9, "kg/t"),
        ("target-carbon", "target_carbon_mass_fraction", 1, "fraction"),
        ("target-oxidation", "target_oxidation_fraction", 1, "fraction"),
    )
    evidence = [parameter(
        *item,
        reference_source_id="stoich-sintered-mullite",
        target_material="electrofused mullite",
        target_process="electrofused",
        accounting_role="CONSUMABLE_ELECTRODE",
        accounting_module="A3_DIRECT_PROCESS",
    ) for item in values]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=InMemoryProcessParameterRepository(evidence),
    ).resolve(request(
        material_name="electrofused mullite", product_form="grain",
        composition="mullite", production_process="electrofused",
    ))

    candidate = result.candidates[0]
    assert candidate.factor_value == pytest.approx(2.734546778, abs=1e-9)
    step = next(item for item in candidate.transformation_steps if item.router_type.value == "PROCESS_VARIANT_RESOLUTION")
    assert step.input_values["target_additional_process"] == pytest.approx(0.033)
    assert step.input_values["target_additional_stoichiometric"] == 1
    assignments = result.accounting_assignments
    assert assignments[0].subject == "electrofused mullite"
    assert assignments[0].role == AccountingRole.TARGET_PRODUCT
    assert assignments[0].modules == ()
    assert any(
        item.role == AccountingRole.CONSUMABLE_ELECTRODE
        and item.modules == (AccountingModule.A1_UPSTREAM_INPUT,)
        and item.quantification_status
        == AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
        and item.missing_inputs == ("consumable_upstream_factor_kgco2e_per_kg",)
        for item in assignments
    )
    assert any(
        item.role == AccountingRole.DIRECT_PROCESS_EMISSION
        and item.modules == (AccountingModule.A3_DIRECT_PROCESS,)
        and item.quantification_status == AccountingQuantificationStatus.QUANTIFIED
        and item.missing_inputs == ()
        for item in assignments
    )
    routed_contributions = tuple(
        item for item in assignments if item.role != AccountingRole.TARGET_PRODUCT
    )
    assert all(
        all("ref-" not in evidence_id for evidence_id in item.evidence_ids)
        for item in routed_contributions
    )


@pytest.mark.asyncio
async def test_process_trigger_without_stoichiometric_bundle_returns_minimum_gap():
    sintered = record(
        "trigger-sintered-mullite", "sintered mullite", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        boundary="cradle-to-gate", metadata={"includes_process": "true"},
    )
    base_values = (
        ("ref-energy", "reference_total_energy_kgce_per_t", 365, "kgce/t"),
        ("ref-elec-share", "reference_electricity_share", 0.76, "fraction"),
        ("ref-gas-share", "reference_natural_gas_share", 0.24, "fraction"),
        ("target-energy", "target_total_energy_kgce_per_t", 165, "kgce/t"),
        ("target-elec-share", "target_electricity_share", 1.0, "fraction"),
        ("elec-coef", "electricity_kgce_per_kwh", 0.1229, "kgce/kWh"),
        ("gas-coef", "natural_gas_kgce_per_nm3", 1.2143, "kgce/Nm3"),
        ("elec-ef", "electricity_ef_kgco2e_per_kwh", 0.5777, "kgCO2e/kWh"),
        ("gas-ef", "natural_gas_ef_kgco2e_per_nm3", 2.792671012566, "kgCO2e/Nm3"),
        ("ref-process-zero", "reference_additional_process_emission_kgco2e_per_kg", 0, "kgCO2e/kg"),
        ("target-trigger", "target_process_emission_calculation_required", 1, "flag"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=InMemoryProcessParameterRepository([
            parameter(
                *item,
                reference_source_id="trigger-sintered-mullite",
                target_material="electrofused mullite",
                target_process="electrofused",
            )
            for item in base_values
        ]),
    ).resolve(request(
        material_name="electrofused mullite", product_form="grain",
        composition="mullite", production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert result.diagnostic_candidates
    assert any("含碳耗材" in question for question in result.questions)
    process_warnings = result.trace.latest("process_variant_resolution").details["warnings"]
    assert any("carbon mass fraction" in warning for warning in process_warnings)


def build_mullite_energy_database(
    path, *, include_scoped_parameters: bool = True, enterprise_profiles=(),
    enterprise_process_emissions=(),
):
    standard_locator = "standard:T/CHNRISC-0008-2025#table-1"
    standard_sha = "cde88c2a57249f8a8753955dcdfa8ba14b966266b6df56adc1ec06374b96323a"
    quotas = [
        EnergyQuotaRecord(
            f"t-chnrisc-0008-2025:t1:sintered-mullite:l{level}",
            "烧结莫来石", "mullite", "sintered", level, value,
            "T/CHNRISC 0008-2025", "1", 6, 2,
            product_group="莫来石", source_locator=standard_locator, source_sha256=standard_sha,
        )
        for level, value in ((1, 365), (2, 400), (3, 415))
    ] + [
        EnergyQuotaRecord(
            f"t-chnrisc-0008-2025:t1:electrofused-mullite:l{level}",
            "电熔莫来石", "mullite", "electrofused", level, value,
            "T/CHNRISC 0008-2025", "1", 6, 2,
            product_group="莫来石", source_locator=standard_locator, source_sha256=standard_sha,
        )
        for level, value in ((1, 165), (2, 174), (3, 185))
    ]
    conversion = EnergyConversionRecord(
        "t-chnrisc-0008-2025:electricity-equivalent",
        "electricity_kgce_per_kwh", "electricity", 0.1229, 0.1229, "kgce/kWh",
        "equivalent_value", ParameterSourceType.FORMAL_STANDARD,
        "河南省耐火材料行业协会", "standard:T/CHNRISC-0008-2025#6.2.4",
        citation="T/CHNRISC 0008-2025 6.2.4", standard_code="T/CHNRISC 0008-2025",
        physical_page=11,
    )
    values = (
        ("ref-elec-share", "reference_electricity_share", 0.76, "fraction"),
        ("ref-gas-share", "reference_natural_gas_share", 0.24, "fraction"),
        ("target-elec-share", "target_electricity_share", 1.0, "fraction"),
        ("target-gas-share", "target_natural_gas_share", 0.0, "fraction"),
        ("gas-coef", "natural_gas_kgce_per_nm3", 1.2143, "kgce/Nm3"),
        ("elec-ef", "electricity_ef_kgco2e_per_kwh", 0.5777, "kgCO2e/kWh"),
        ("gas-ef", "natural_gas_ef_kgco2e_per_nm3", 2.792671012566, "kgCO2e/Nm3"),
    )
    process = [
        ScopedProcessParameterRecord(
            parameter_id, name, value, unit,
            ParameterSourceType.USER_CONFIRMED_ENGINEERING_DATA,
            "electrofused mullite engineering memo", "memo:electrofused-mullite-2026-08-12",
            "mullite", "sintered", "mullite", "electrofused",
            reference_source_id="formal-sintered-mullite",
            quality_note="independent engineering evidence; not supplied by the energy-quota standard",
            metadata=(
                {"reference_includes_process": "true"}
                if parameter_id == "ref-elec-share" else {}
            ),
        )
        for parameter_id, name, value, unit in values
    ] if include_scoped_parameters else []
    return create_energy_database(
        path,
        database_name="refractory-energy-parameters.db",
        dataset_version="t-chnrisc-0008-2025/v1",
        source_standard_code="T/CHNRISC 0008-2025",
        source_sha256=standard_sha,
        source_locator=standard_locator,
        quotas=quotas,
        conversions=(conversion,),
        process_parameters=process,
        enterprise_profiles=enterprise_profiles,
        enterprise_process_emissions=enterprise_process_emissions,
    )


def enterprise_profile(
    profile_id: str,
    product_name: str,
    canonical_product: str,
    process: str,
    total_energy: float,
    electricity_share: float,
    remainder_carrier: str,
    *,
    runtime_eligible: bool = True,
    head_material: str = "mullite",
    product_group: str = "莫来石",
) -> EnterpriseEnergyProfileRecord:
    return EnterpriseEnergyProfileRecord(
        profile_id=profile_id,
        sequence_id=profile_id,
        product_name=product_name,
        product_group=product_group,
        head_material=head_material,
        production_process=process,
        quota_level=1,
        total_energy_kgce_per_t=total_energy,
        electricity_share=electricity_share,
        remainder_carrier=remainder_carrier,
        remainder_share=1 - electricity_share,
        source_type=ParameterSourceType.USER_CONFIRMED_ENGINEERING_DATA,
        provider="enterprise workbook",
        locator="workbook:enterprise-energy.xlsx#Sheet1",
        worksheet_name="Sheet1",
        worksheet_row=5,
        energy_cell="D5",
        electricity_share_cell="J5",
        formula_cell="M5",
        canonical_product=canonical_product,
        citation="enterprise workbook Sheet1 row 5",
        quality_note="user-provided enterprise energy allocation",
        allocation_status=(
            "ALL_ELECTRIC" if remainder_carrier == "none"
            else f"ELECTRICITY_{remainder_carrier.upper()}"
        ),
        source_sha256="a" * 64,
        runtime_eligible=runtime_eligible,
    )


def enterprise_process_emission(
    emission_id: str,
    product_name: str,
    canonical_product: str,
    process: str,
    value_kgco2e_per_t: float,
    *,
    head_material: str = "spinel",
    runtime_eligible: bool = False,
) -> EnterpriseProcessEmissionRecord:
    return EnterpriseProcessEmissionRecord(
        emission_id=emission_id,
        sequence_id=emission_id,
        product_name=product_name,
        canonical_product=canonical_product,
        head_material=head_material,
        production_process=process,
        quota_level=1,
        emission_name=(
            "direct_electrode_oxidation_co2"
            if value_kgco2e_per_t else "additional_direct_process_co2"
        ),
        value_kgco2e_per_t=value_kgco2e_per_t,
        source_type=ParameterSourceType.USER_CONFIRMED_ENGINEERING_DATA,
        provider="enterprise workbook",
        locator="workbook:enterprise-energy.xlsx#Sheet1",
        worksheet_name="Sheet1",
        worksheet_row=61 if process == "electrofused" else 64,
        emission_cell="P61" if process == "electrofused" else "P64",
        formula="9*44/12" if value_kgco2e_per_t else "",
        citation="enterprise workbook process emission",
        quality_note="electrode oxidation process emission",
        source_sha256="a" * 64,
        runtime_eligible=runtime_eligible,
    )


@pytest.mark.asyncio
async def test_sqlite_energy_database_uses_level_one_and_rebuilds_mullite(tmp_path):
    database = tmp_path / "energy.db"
    anchor = build_mullite_energy_database(database)
    sintered = record(
        "formal-sintered-mullite", "烧结莫来石", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        boundary="cradle-to-gate", declared_product="烧结莫来石",
        boundary_modules=("A1", "A2", "A3"), metadata={},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(
            database, expected_database_sha256=anchor.database_sha256
        ),
    ).resolve(request(
        material_name="电熔莫来石", product_form="grain", composition="mullite",
        production_process="electrofused",
    ))

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.PROCESS_ADJUSTED
    assert candidate.factor_value == pytest.approx(2.701546778, abs=1e-9)
    assert candidate.result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS
    process_trace = result.trace.latest("process_variant_resolution").details
    assert process_trace["parameter_databases"][0]["database_sha256"] == anchor.database_sha256
    assert result.trace.explain()["parameter_databases"][0]["database_sha256"] == anchor.database_sha256
    evidence = {item["name"]: item for item in process_trace["parameter_evidence"]}
    assert evidence["reference_total_energy_kgce_per_t"]["value"] == 365
    assert evidence["target_total_energy_kgce_per_t"]["value"] == 165
    assert evidence["target_total_energy_kgce_per_t"]["metadata"]["quota_level"] == "1"


@pytest.mark.asyncio
async def test_energy_quota_database_does_not_invent_missing_route_mix(tmp_path):
    database = tmp_path / "quota-only.db"
    build_mullite_energy_database(database, include_scoped_parameters=False)
    sintered = record(
        "formal-sintered-mullite", "烧结莫来石", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        declared_product="烧结莫来石", boundary_modules=("A1", "A2", "A3"),
        metadata={"includes_process": "true"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(database),
    ).resolve(request(
        material_name="电熔莫来石", product_form="grain", composition="mullite",
        production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    evidence_names = {
        item["name"] for item in result.trace.latest("process_variant_resolution").details["parameter_evidence"]
    }
    assert evidence_names == {
        "reference_total_energy_kgce_per_t",
        "target_total_energy_kgce_per_t",
        "electricity_kgce_per_kwh",
    }


@pytest.mark.asyncio
async def test_enterprise_profiles_supply_exact_closed_route_shares(tmp_path):
    database = tmp_path / "enterprise-profile.db"
    profiles = (
        enterprise_profile(
            "enterprise-sintered", "烧结莫来石", "sintered mullite",
            "sintered", 365, 0.24, "natural_gas",
        ),
        enterprise_profile(
            "enterprise-electrofused", "电熔莫来石", "electrofused mullite",
            "electrofused", 165, 1.0, "none",
        ),
    )
    build_mullite_energy_database(
        database, enterprise_profiles=profiles,
    )
    sintered = record(
        "formal-sintered-mullite", "烧结莫来石", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        declared_product="烧结莫来石", boundary_modules=("A1", "A2", "A3"),
        metadata={"includes_process": "true"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(database),
    ).resolve(request(
        material_name="电熔莫来石", product_form="grain", composition="mullite",
        production_process="electrofused",
    ))

    evidence = {
        item["name"]: item
        for item in result.trace.latest("process_variant_resolution").details["parameter_evidence"]
    }
    assert evidence["reference_electricity_share"]["value"] == pytest.approx(0.24)
    assert evidence["reference_natural_gas_share"]["value"] == pytest.approx(0.76)
    assert evidence["target_electricity_share"]["value"] == pytest.approx(1.0)
    assert evidence["target_natural_gas_share"]["value"] == pytest.approx(0.0)
    assert evidence["target_electricity_share"]["metadata"][
        "enterprise_energy_profile_id"
    ] == "enterprise-electrofused"
    assert evidence["target_electricity_share"]["metadata"][
        "source_workbook_sha256"
    ] == "a" * 64
    assert evidence["reference_process_inclusion"]["value"] == 1.0
    assert result.candidates[0].resolution_type == ResolutionType.PROCESS_ADJUSTED


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier,runtime_eligible", (("standard_coal", True),))
async def test_unsupported_enterprise_profile_cannot_activate_shares(
    tmp_path, carrier, runtime_eligible,
):
    database = tmp_path / f"blocked-{carrier}.db"
    profiles = (
        enterprise_profile(
            "enterprise-sintered", "烧结莫来石", "sintered mullite",
            "sintered", 365, 0.76, "natural_gas",
        ),
        enterprise_profile(
            "enterprise-electrofused", "电熔莫来石", "electrofused mullite",
            "electrofused", 165, 0.8, carrier, runtime_eligible=runtime_eligible,
        ),
    )
    build_mullite_energy_database(
        database, include_scoped_parameters=False, enterprise_profiles=profiles,
    )
    sintered = record(
        "formal-sintered-mullite", "烧结莫来石", 3.431355,
        product_form="grain", composition="mullite", production_process="sintered",
        declared_product="烧结莫来石", boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(database),
    ).resolve(request(
        material_name="电熔莫来石", product_form="grain", composition="mullite",
        production_process="electrofused",
    ))

    evidence_names = {
        item["name"]
        for item in result.trace.latest("process_variant_resolution").details["parameter_evidence"]
    }
    assert not evidence_names & {
        "reference_electricity_share",
        "reference_natural_gas_share",
        "target_electricity_share",
        "target_natural_gas_share",
    }


@pytest.mark.asyncio
async def test_energy_quota_scope_never_applies_mullite_route_to_other_material(tmp_path):
    database = tmp_path / "scoped.db"
    build_mullite_energy_database(database)
    other = record(
        "ecoinvent-sintered-mullite-proxy", "烧结莫来石（高铝耐火材料生产代理）", 0.619377914,
        product_form="packed refractory", composition="high aluminium oxide",
        production_process="sintered", declared_product="高铝耐火材料",
        boundary_modules=("A1", "A2", "A3"), metadata={"includes_process": "true"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([other]),
        process_parameters=SqliteEnergyProcessParameterRepository(database),
    ).resolve(request(
        material_name="电熔莫来石", product_form="grain", composition="mullite",
        production_process="electrofused",
    ))

    assert all(candidate.factor_value != pytest.approx(2.701546778) for candidate in result.candidates)
    assert all(candidate.resolution_type != ResolutionType.PROCESS_ADJUSTED for candidate in result.candidates)
    process_trace = result.trace.latest("process_variant_resolution")
    if process_trace:
        evidence_names = {item["name"] for item in process_trace.details["parameter_evidence"]}
        assert {
            "reference_total_energy_kgce_per_t",
            "target_total_energy_kgce_per_t",
            "electricity_kgce_per_kwh",
        } <= evidence_names


@pytest.mark.asyncio
async def test_database_priority_policy_rebuilds_electrofused_spinel_with_trace(
    tmp_path,
):
    database = tmp_path / "spinel-database-priority.db"
    profiles = (
        enterprise_profile(
            "enterprise-sintered-spinel", "烧结镁铝尖晶石", "sintered spinel",
            "sintered", 375, 0.021, "natural_gas", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
        enterprise_profile(
            "enterprise-electrofused-spinel", "电熔镁铝尖晶石", "electrofused spinel",
            "electrofused", 185, 1.0, "none", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
    )
    process_emissions = (
        enterprise_process_emission(
            "enterprise-sintered-spinel-process", "烧结镁铝尖晶石",
            "sintered spinel", "sintered", 0,
        ),
        enterprise_process_emission(
            "enterprise-electrofused-spinel-electrode", "电熔镁铝尖晶石",
            "electrofused spinel", "electrofused", 33,
        ),
    )
    build_mullite_energy_database(
        database,
        enterprise_profiles=profiles,
        enterprise_process_emissions=process_emissions,
    )
    sintered = record(
        "formal-sintered-spinel", "烧结尖晶石", 4.602431,
        product_form="grain", composition="magnesia alumina spinel",
        production_process="sintered", declared_product="烧结尖晶石",
        boundary_modules=("A1", "A2", "A3"),
    )
    broad_proxy = record(
        "ecoinvent-sintered-spinel-proxy",
        "烧结尖晶石（高铝耐火材料生产代理）",
        0.619377914,
        product_form="packed refractory",
        composition="high aluminium oxide",
        production_process="sintered",
        declared_product="高铝耐火材料",
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered, broad_proxy]),
        process_parameters=SqliteEnergyProcessParameterRepository(
            database,
            allow_review_profiles=True,
            allow_generic_energy_parameters=True,
            assume_lifecycle_process_inclusion=True,
        ),
    ).resolve(request(
        material_name="电熔尖晶石", product_form="grain",
        composition="magnesia alumina spinel", production_process="electrofused",
    ))

    candidate = next(
        item for item in result.candidates
        if item.source.source_id == "formal-sintered-spinel"
    )
    assert candidate.factor_value == pytest.approx(4.62369809236118)
    assert candidate.dimensions["material"] == 1.0
    assert candidate.resolved_quantity_kg == pytest.approx(1000.0)
    assert candidate.total_emissions_kgco2e == pytest.approx(4623.69809236118)
    assert any(
        step.formula_id == "process.replace_energy_and_additional_process/v2"
        for step in candidate.transformation_steps
    )
    assert any("marked for review" in item for item in candidate.assumptions)
    assert any(
        "process-emission records marked for review" in item
        for item in candidate.assumptions
    )
    assert any("reused across material routes" in item for item in candidate.assumptions)
    assert any("assumed to include route energy" in item for item in candidate.assumptions)
    process_entry = next(
        entry for entry in result.trace.entries
        if entry.stage == "process_variant_resolution"
        and any(
            item["metadata"].get("reference_source_id") == "formal-sintered-spinel"
            for item in entry.details["parameter_evidence"]
        )
    )
    evidence_items = process_entry.details["parameter_evidence"]
    evidence = {
        item["name"]: item
        for item in evidence_items
        if item["metadata"].get("reference_source_id") == "formal-sintered-spinel"
    }
    assert evidence["reference_total_energy_kgce_per_t"]["value"] == 375
    assert evidence["reference_electricity_share"]["value"] == pytest.approx(0.021)
    assert evidence["target_total_energy_kgce_per_t"]["value"] == 185
    assert evidence["target_electricity_share"]["value"] == 1.0
    assert evidence[
        "reference_additional_process_emission_kgco2e_per_kg"
    ]["value"] == 0.0
    target_process_emission = evidence[
        "target_additional_process_emission_kgco2e_per_kg"
    ]
    assert target_process_emission["value"] == pytest.approx(0.033)
    assert target_process_emission["metadata"]["raw_value_kgco2e_per_t"] == "33"
    assert "P61" in target_process_emission["metadata"]["emission_cells"]
    process_step = next(
        step for step in candidate.transformation_steps
        if step.formula_id == "process.replace_energy_and_additional_process/v2"
    )
    assert process_step.input_values["target_additional_process"] == pytest.approx(0.033)
    assert evidence["reference_process_inclusion"]["metadata"][
        "process_inclusion_basis"
    ] == "policy_assumption"
    assert evidence["natural_gas_ef_kgco2e_per_nm3"]["metadata"][
        "parameter_scope"
    ] == "unique_generic_energy_carrier_fallback"
    assert all(
        item.source.source_id != "ecoinvent-sintered-spinel-proxy"
        for item in result.candidates
    )
    assert any(
        item["source_id"] == "ecoinvent-sintered-spinel-proxy"
        for item in result.trace.explain()["excluded_candidates"]
    )


@pytest.mark.asyncio
async def test_review_energy_profiles_are_disabled_by_default(tmp_path):
    database = tmp_path / "review-profiles-disabled.db"
    profiles = (
        enterprise_profile(
            "review-ref", "烧结镁铝尖晶石", "sintered spinel", "sintered",
            375, 0.021, "natural_gas", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
        enterprise_profile(
            "review-target", "电熔镁铝尖晶石", "electrofused spinel", "electrofused",
            185, 1.0, "none", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
    )
    build_mullite_energy_database(database, enterprise_profiles=profiles)
    sintered = record(
        "formal-sintered-spinel-safe-default", "烧结尖晶石", 4.602431,
        product_form="grain", composition="magnesia alumina spinel",
        production_process="sintered", declared_product="烧结尖晶石",
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(database),
    ).resolve(request(
        material_name="电熔尖晶石", product_form="grain",
        composition="magnesia alumina spinel", production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_additional_process_replacement_requires_bilateral_records(tmp_path):
    database = tmp_path / "one-sided-process-emission.db"
    profiles = (
        enterprise_profile(
            "one-sided-ref", "烧结镁铝尖晶石", "sintered spinel", "sintered",
            375, 0.021, "natural_gas", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
        enterprise_profile(
            "one-sided-target", "电熔镁铝尖晶石", "electrofused spinel", "electrofused",
            185, 1.0, "none", runtime_eligible=False,
            head_material="spinel", product_group="镁铝尖晶石",
        ),
    )
    process_emissions = (
        enterprise_process_emission(
            "reference-positive-only", "烧结镁铝尖晶石",
            "sintered spinel", "sintered", 200,
        ),
    )
    build_mullite_energy_database(
        database,
        enterprise_profiles=profiles,
        enterprise_process_emissions=process_emissions,
    )
    sintered = record(
        "formal-one-sided-spinel", "烧结尖晶石", 4.0,
        product_form="grain", composition="magnesia alumina spinel",
        production_process="sintered", declared_product="烧结尖晶石",
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sintered]),
        process_parameters=SqliteEnergyProcessParameterRepository(
            database,
            allow_review_profiles=True,
            allow_generic_energy_parameters=True,
            assume_lifecycle_process_inclusion=True,
        ),
    ).resolve(request(
        material_name="电熔尖晶石", product_form="grain",
        composition="magnesia alumina spinel", production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any(
        "requires explicit records for both reference and target routes" in warning
        for warning in result.trace.explain()["warnings"]
    )


@pytest.mark.asyncio
async def test_process_router_does_not_add_process_energy_without_supported_removal():
    finished = record(
        "finished-product", "electrofused alumina product", 4.0,
        production_process="finished refractory production",
        metadata={"system_role": "finished_product"},
    )
    only_added = [parameter(
        "added", "added_process_factor", 0.8, "kgCO2e/kg",
        reference_source_id="finished-product", target_material="electrofused alumina",
        target_process="electrofused",
    )]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([finished]),
        process_parameters=InMemoryProcessParameterRepository(only_added),
    ).resolve(request(material_name="electrofused alumina", production_process="electrofused"))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_grade_router_interpolates_only_between_same_series_anchors():
    grade_90 = record(
        "magnesia-90", "magnesia", 1.0, composition="90% MgO",
        production_process="sintered", provider="series provider",
        declared_product="magnesia", boundary_modules=("A1", "A2", "A3"),
        metadata={"series_id": "sintered magnesia", "grade": "90"},
    )
    grade_97 = record(
        "magnesia-97", "magnesia 97", 1.7, composition="97% MgO",
        production_process="sintered", provider="series provider",
        declared_product="magnesia", boundary_modules=("A1", "A2", "A3"),
        metadata={"series_id": "sintered magnesia", "grade": "97"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([grade_90]),
        grade_series=InMemoryGradeSeriesRepository([grade_97]),
    ).resolve(request(
        material_name="magnesia", composition="95% MgO",
        production_process="sintered",
    ))

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.GRADE_INTERPOLATED
    assert candidate.factor_value == pytest.approx(1.5)
    assert candidate.base_source_ids == ("magnesia-90", "magnesia-97")
    assert any(step.formula_id == "grade.linear_interpolation_same_series/v1" for step in candidate.transformation_steps)


@pytest.mark.asyncio
async def test_single_grade_is_returned_unchanged_as_grade_proxy():
    grade_90 = record(
        "magnesia-90", "magnesia", 1.0, composition="90% MgO",
        production_process="sintered", metadata={"grade": "90"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([grade_90]),
    ).resolve(request(material_name="magnesia", composition="95% MgO", production_process="sintered"))

    candidate = result.diagnostic_candidates[0]
    assert candidate.resolution_type == ResolutionType.GRADE_PROXY
    assert candidate.factor_value == 1.0
    assert any("+5 percentage points" in limitation for limitation in candidate.limitations)


@pytest.mark.asyncio
async def test_material_absence_uses_class_aware_top_k_without_hardcoded_proxy():
    proxies = [
        record("kyanite", "kyanite", 0.3, composition="aluminosilicate", production_process="mining", metadata={"material_class": "andalusite", "family": "inorganics"}),
        record("sillimanite", "sillimanite", 0.4, composition="aluminosilicate", production_process="mining", metadata={"material_class": "andalusite", "family": "inorganics"}),
        record("kaolin", "kaolin", 0.2, composition="aluminosilicate", production_process="mining", metadata={"material_class": "andalusite", "family": "inorganics"}),
    ]
    result = await A1FactorResolutionEngine(
        proxy_retrieval=InMemoryProxyRepository(proxies),
    ).resolve(request(
        material_name="andalusite", composition="aluminosilicate",
        production_process="mining", top_k=3,
    ))

    assert len(result.candidates) == 3
    assert {candidate.source.source_id for candidate in result.candidates} == {"kyanite", "sillimanite", "kaolin"}
    assert all(candidate.resolution_type == ResolutionType.CLASS_TECHNICAL_PROXY for candidate in result.candidates)


@pytest.mark.asyncio
async def test_multi_gap_plan_executes_reference_flow_before_process_before_grade():
    source = record(
        "fused-90", "90% fused magnesia", 1.0,
        product_form="grain", composition="90% MgO", production_process="fused",
    )
    flow = ReferenceFlowRecord(
        "bag-mass", "95% sintered magnesia", "bag", 25,
        parameter("bag-mass-p", "mass_per_bag", 25, "kg/bag"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        reference_flows=InMemoryReferenceFlowRepository([flow]),
    ).resolve(request(
        material_name="95% sintered magnesia", quantity=2, quantity_unit="bag",
        product_form="grain", composition="95% MgO", production_process="sintered",
    ))

    stages = [entry.stage for entry in result.trace.entries]
    assert stages.index("reference_flow_resolution") < stages.index("process_variant_resolution")
    assert stages.index("process_variant_resolution") < stages.index("grade_composition_resolution")
    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert result.trace.latest("reference_flow_resolution").details["candidate_ids"]


@pytest.mark.asyncio
async def test_class_proxy_still_requires_reference_flow_evidence_for_piece_activity():
    proxy = record(
        "generic-mineral", "generic mineral", 0.2,
        production_process="mining",
        metadata={"material_class": "andalusite", "family": "natural minerals"},
    )
    result = await A1FactorResolutionEngine(
        proxy_retrieval=InMemoryProxyRepository([proxy]),
    ).resolve(request(
        material_name="andalusite", quantity=10, quantity_unit="piece",
        production_process="mining",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.candidates == ()
    assert result.trace.explain()["required_fields"] == ("mass_per_piece", "dimensions+density")


@pytest.mark.asyncio
async def test_delta_adjustment_cannot_subtract_process_absent_from_source_boundary():
    source = record(
        "raw-upstream", "calcined alumina", 2.0,
        production_process="calcined",
        metadata={"includes_process": "false"},
    )
    evidence = [
        parameter("remove", "removed_process_factor", 0.4, "kgCO2e/kg", reference_source_id="raw-upstream", target_material="fused alumina", target_process="fused"),
        parameter("add", "added_process_factor", 0.7, "kgCO2e/kg", reference_source_id="raw-upstream", target_material="fused alumina", target_process="fused"),
    ]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(evidence),
    ).resolve(request(material_name="fused alumina", production_process="fused"))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any("includes it" in warning for warning in result.trace.explain()["warnings"])


@pytest.mark.asyncio
async def test_t01_broad_steel_fiber_returns_more_input_with_provisional_options():
    result = await A1FactorResolutionEngine().resolve(
        ResolutionRequest(material_name="steel fiber", quantity=1, product_form="fiber")
    )
    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    explanation = result.trace.explain()
    assert explanation["material_identity"]["category"] == "METAL"
    assert explanation["required_choice"]["field"] == "steel_fiber_type"
    assert len(explanation["provisional_options"]) == 3


@pytest.mark.asyncio
async def test_broad_steel_fiber_keeps_qualified_record_reference_only() -> None:
    source = replace(
        record(
            "generic-steel-fiber-product",
            "steel fiber",
            2.16,
            product_form="fiber",
            factor_kind=FactorKind.EPD_INDICATOR,
            indicator="GWP-total",
            declared_product="steel fiber",
        ),
        subject_type=FactorSubjectType.FINISHED_PRODUCT,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    ).resolve(
        ResolutionRequest(
            material_name="steel fiber",
            quantity=1,
            product_form="fiber",
            subject_type=FactorSubjectType.FINISHED_PRODUCT,
            boundary="cradle-to-gate",
        )
    )

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.candidates == ()
    assert [item.source.source_id for item in result.reviewable_candidates] == [
        "generic-steel-fiber-product"
    ]
    assert result.reviewable_candidates[0].result_tier == ResultTier.REFERENCE_ONLY
    assert result.trace.explain()["required_choice"]["field"] == "steel_fiber_type"


@pytest.mark.asyncio
async def test_t01_chinese_steel_fiber_identity_is_not_unknown():
    result = await A1FactorResolutionEngine().resolve(
        ResolutionRequest(material_name="钢纤维", quantity=1, product_form="纤维")
    )
    identity = result.trace.explain()["material_identity"]
    assert identity["head_material"] == "steel"
    assert identity["category"] == "METAL"
    assert identity["product_form"] == "fiber"


@pytest.mark.asyncio
async def test_t04_446_identity_is_metal_ferritic_stainless_and_grade_specific():
    result = await A1FactorResolutionEngine().resolve(
        ResolutionRequest(material_name="446 heat resistant steel fiber", quantity=1, product_form="fiber")
    )
    identity = result.trace.explain()["material_identity"]
    assert identity["category"] == "METAL"
    assert identity["material_family"] == "ferritic_stainless_steel"
    assert identity["grade"] == "AISI 446 / UNS S44600"


@pytest.mark.asyncio
async def test_t06_form_only_related_hit_is_raw_observation_only():
    alumina_limit = record(
        "al-limit", "aluminosilicate refractory fiber", 1.0, unit="kgCO2e/t产品",
        product_form="fiber", factor_kind=FactorKind.EMISSION_LIMIT,
        indicator="GWP-total", declared_product="aluminosilicate refractory fiber",
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([alumina_limit])
    ).resolve(ResolutionRequest(material_name="steel fiber", quantity=1, product_form="fiber"))
    # Entity-resolved requests do not perform form-only lexical recall.
    assert result.trace.explain()["raw_related_hits"] == ()
    assert result.trace.explain()["local_retrieval"]["record_count"] == 0
    assert result.candidates == ()


def test_t08_and_t09_product_qualifier_is_parsed_but_factor_kind_still_qualifies():
    parsed = parse_factor_unit("kgCO2e/t产品")
    assert parsed.numerator == "kg" and parsed.denominator_mass == "t"
    assert parsed.reference_product_qualifier == "产品"


@pytest.mark.asyncio
async def test_t07_emission_limit_is_excluded_even_when_unit_is_parseable():
    limit = record("limit", "steel fiber", 1.0, unit="kgCO2e/t产品", factor_kind=FactorKind.EMISSION_LIMIT,
                   indicator="GWP-total", declared_product="steel fiber", boundary_modules=("A1", "A2", "A3"))
    result = await A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([limit])).resolve(
        ResolutionRequest(material_name="steel fiber", quantity=1, product_form="fiber")
    )
    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert any(item["factor_kind"]["status"] == "mismatch" for item in result.trace.explain()["record_qualifications"])


@pytest.mark.asyncio
async def test_t11_provisional_and_t12_reference_only_are_not_standard_lockable():
    reference = record("ref", "steel coil", 1.0)
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([reference]))
    result = await engine.resolve(ResolutionRequest(material_name="premium steel coil", quantity=1))
    assert result.candidates == ()
    candidate = result.reviewable_candidates[0]
    assert candidate.result_tier == ResultTier.REFERENCE_ONLY
    with pytest.raises(ValueError):
        await engine.approve(
            result.request_id, candidate.candidate_id, "reviewer"
        )


@pytest.mark.asyncio
async def test_t13_reference_override_is_recorded_and_can_lock():
    reference = record("ref", "steel coil", 1.0)
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([reference]))
    result = await engine.resolve(ResolutionRequest(material_name="premium steel coil", quantity=1))
    candidate = result.reviewable_candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer", "family reference accepted", ApprovalMode.REFERENCE_OVERRIDE)
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    assert locked.approval.mode == ApprovalMode.REFERENCE_OVERRIDE
    assert engine is not None


@pytest.mark.asyncio
async def test_t14_exact_steel_epd_does_not_enter_proxy():
    epd = record("steel-epd", "steel fiber without copper plating", 0.93,
                 factor_kind=FactorKind.EPD_INDICATOR, indicator="GWP-total",
                 declared_product="steel fiber without copper plating", boundary_modules=("A1", "A2", "A3"),
                 product_form="fiber")
    class ExplodingProxy:
        async def search(self, activity, material_class):
            raise AssertionError("exact EPD must not enter proxy")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([epd]), proxy_retrieval=ExplodingProxy()
    ).resolve(ResolutionRequest(material_name="steel fiber without copper plating", quantity=1, product_form="fiber"))
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].factor_value == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_t03_copper_plated_epd_is_a_separate_direct_record():
    epd = record("steel-epd-copper", "steel fiber with copper plating", 1.27,
                 factor_kind=FactorKind.EPD_INDICATOR, indicator="GWP-total",
                 declared_product="steel fiber with copper plating", boundary_modules=("A1", "A2", "A3"),
                 product_form="fiber")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([epd])
    ).resolve(ResolutionRequest(material_name="steel fiber with copper plating", quantity=1, product_form="fiber"))
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].factor_value == pytest.approx(1.27)


@pytest.mark.asyncio
async def test_t16_trace_uses_no_evaluable_candidates_wording():
    result = await A1FactorResolutionEngine().resolve(ResolutionRequest(material_name="unknown composite", quantity=1))
    route = result.trace.latest("local_evaluate")
    assert route is not None
    assert "no evaluable candidates" in route.message


@pytest.mark.asyncio
async def test_more_input_route_is_not_overwritten_by_proxy_or_unresolved():
    result = await A1FactorResolutionEngine().resolve(
        ResolutionRequest(material_name="钢纤维", quantity=1, product_form="纤维")
    )
    explanation = result.trace.explain()
    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert explanation["proxy_decision"]["decision"] == "more_input"
    assert all(item["strategy"] != "unresolved" for item in explanation["link_attempts"])


@pytest.mark.asyncio
async def test_product_qualified_unit_requires_declared_product_before_conversion():
    qualified_unit_without_product = record(
        "qualified-unit-missing-product",
        "steel coil",
        1000,
        unit="kgCO2e/t产品",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        indicator="GWP-total",
        declared_product=None,
        boundary_modules=("A1", "A2", "A3"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([qualified_unit_without_product])
    ).resolve(request())
    qualification = result.trace.explain()["record_qualifications"][0]
    assert qualification["eligible"] is False
    assert qualification["declared_product"]["status"] == "mismatch"
    assert qualification["unit"]["status"] == "unknown"
    assert "unit_qualifier_requires_validation" in qualification["additional_exclusions"]


@pytest.mark.asyncio
async def test_incompatible_boundary_modules_fail_before_candidate_conversion():
    a4_only = record(
        "a4-only",
        "steel coil",
        1.0,
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        indicator="GWP-total",
        declared_product="steel coil",
        boundary_modules=("A4",),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([a4_only])
    ).resolve(request())
    qualification = result.trace.explain()["record_qualifications"][0]
    assert qualification["eligible"] is False
    assert qualification["boundary"]["status"] == "mismatch"
    assert qualification["primary_exclusion"] == "boundary_mismatch"


@pytest.mark.asyncio
async def test_usable_with_assumptions_requires_acceptance_mode_and_can_lock():
    factor = record("brick-factor-approval", "refractory brick", 1.5, product_form="brick")
    flow = ReferenceFlowRecord(
        "measured-approval",
        "refractory brick",
        "piece",
        4.2,
        parameter("mass-approval", "mass_per_piece", 4.2, "kg/piece"),
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([factor]),
        reference_flows=InMemoryReferenceFlowRepository([flow]),
    )
    result = await engine.resolve(request(
        material_name="refractory brick",
        quantity=100,
        quantity_unit="piece",
        product_form="brick",
    ))
    candidate = result.candidates[0]
    assert candidate.result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS
    with pytest.raises(ValueError):
        await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    approval = await engine.approve(
        result.request_id,
        candidate.candidate_id,
        "reviewer",
        "process difference accepted",
        ApprovalMode.ASSUMPTION_ACCEPTANCE,
    )
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    assert approval.mode == ApprovalMode.ASSUMPTION_ACCEPTANCE
    assert locked.approval.mode == ApprovalMode.ASSUMPTION_ACCEPTANCE


def scoped_process_parameters(
    *,
    reference_source_id: str,
    target_material: str,
    target_process: str,
    target_electricity_share: float = 1.0,
) -> list[ParameterEvidence]:
    values = (
        ("ref-energy", "reference_total_energy_kgce_per_t", 365, "kgce/t"),
        ("ref-elec-share", "reference_electricity_share", 0.76, "fraction"),
        ("ref-gas-share", "reference_natural_gas_share", 0.24, "fraction"),
        ("target-energy", "target_total_energy_kgce_per_t", 165, "kgce/t"),
        ("target-elec-share", "target_electricity_share", target_electricity_share, "fraction"),
        ("elec-coef", "electricity_kgce_per_kwh", 0.1229, "kgce/kWh"),
        ("gas-coef", "natural_gas_kgce_per_nm3", 1.2143, "kgce/Nm3"),
        ("elec-ef", "electricity_ef_kgco2e_per_kwh", 0.5777, "kgCO2e/kWh"),
        ("gas-ef", "natural_gas_ef_kgco2e_per_nm3", 2.792671012566, "kgCO2e/Nm3"),
    )
    return [
        parameter(
            *item,
            reference_source_id=reference_source_id,
            target_material=target_material,
            target_process=target_process,
        )
        for item in values
    ]


@pytest.mark.asyncio
async def test_process_rejects_negative_common_upstream():
    source = record(
        "negative-upstream",
        "sintered mullite",
        0.1,
        composition="mullite",
        production_process="sintered",
        metadata={"includes_process": "true"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(scoped_process_parameters(
            reference_source_id=source.source_id,
            target_material="electrofused mullite",
            target_process="electrofused",
        )),
    ).resolve(request(
        material_name="electrofused mullite",
        composition="mullite",
        production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any("negative common upstream" in warning for warning in result.trace.explain()["warnings"])


@pytest.mark.asyncio
async def test_target_energy_shares_cannot_silently_drop_energy():
    source = record(
        "incomplete-energy",
        "sintered mullite",
        3.5,
        composition="mullite",
        production_process="sintered",
        metadata={"includes_process": "true"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(scoped_process_parameters(
            reference_source_id=source.source_id,
            target_material="electrofused mullite",
            target_process="electrofused",
            target_electricity_share=0.6,
        )),
    ).resolve(request(
        material_name="electrofused mullite",
        composition="mullite",
        production_process="electrofused",
    ))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any(
        "target process energy shares must sum to one" in warning
        for warning in result.trace.explain()["warnings"]
    )


@pytest.mark.asyncio
async def test_process_evidence_without_scope_matches_nothing():
    source = record(
        "scoped-source",
        "calcined alumina",
        2.0,
        production_process="calcined",
        metadata={"includes_process": "true"},
    )
    unscoped = [
        parameter("remove-unscoped", "removed_process_factor", 0.4, "kgCO2e/kg"),
        parameter("add-unscoped", "added_process_factor", 0.7, "kgCO2e/kg"),
    ]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(unscoped),
    ).resolve(request(material_name="fused alumina", production_process="fused"))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert result.trace.latest("process_variant_resolution").details["parameter_ids"] == ()


@pytest.mark.asyncio
async def test_missing_includes_process_never_defaults_to_true():
    source = record(
        "missing-inclusion",
        "calcined alumina",
        2.0,
        production_process="calcined",
        metadata={},
    )
    evidence = [
        parameter(
            "remove-scoped",
            "removed_process_factor",
            0.4,
            "kgCO2e/kg",
            reference_source_id=source.source_id,
            target_material="fused alumina",
            target_process="fused",
        ),
        parameter(
            "add-scoped",
            "added_process_factor",
            0.7,
            "kgCO2e/kg",
            reference_source_id=source.source_id,
            target_material="fused alumina",
            target_process="fused",
        ),
    ]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(evidence),
    ).resolve(request(material_name="fused alumina", production_process="fused"))

    assert result.status == ResolutionStatus.PROCESS_MODEL_REQUIRED
    assert result.candidates == ()
    assert any("explicit evidence" in warning for warning in result.trace.explain()["warnings"])


def qualified_grade_record(source_id: str, grade: float, value: float, *, series_id: str) -> SourceRecord:
    return record(
        source_id,
        f"magnesia {grade:g}%",
        value,
        composition=f"{grade:g}% MgO",
        production_process="sintered",
        provider="grade registry",
        declared_product="magnesia",
        boundary_modules=("A1", "A2", "A3"),
        metadata={"series_id": series_id, "grade": f"{grade:g}"},
    )


@pytest.mark.asyncio
async def test_exact_grade_anchor_is_selected_before_interpolation():
    base = qualified_grade_record("magnesia-90-base", 90, 1.0, series_id="magnesia-series")
    exact = qualified_grade_record("magnesia-95-exact", 95, 1.45, series_id="magnesia-series")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([base]),
        grade_series=InMemoryGradeSeriesRepository([exact]),
    ).resolve(request(material_name="magnesia 90%", composition="95% MgO", production_process="sintered"))

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.GRADE_EXACT_ANCHOR
    assert candidate.source.source_id == exact.source_id
    assert candidate.factor_value == pytest.approx(1.45)


@pytest.mark.asyncio
async def test_grade_anchor_must_have_same_series_id():
    base = qualified_grade_record("magnesia-series-a", 90, 1.0, series_id="series-a")
    wrong = qualified_grade_record("magnesia-series-b", 95, 9.9, series_id="series-b")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([base]),
        grade_series=InMemoryGradeSeriesRepository([wrong]),
    ).resolve(request(material_name="magnesia 90%", composition="95% MgO", production_process="sintered"))

    assert result.diagnostic_candidates[0].resolution_type == ResolutionType.GRADE_PROXY
    assert result.diagnostic_candidates[0].factor_value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_emission_limit_cannot_be_grade_anchor():
    base = qualified_grade_record("magnesia-life-90", 90, 1.0, series_id="series-limit-test")
    limit = record(
        "magnesia-limit-95",
        "magnesia 95%",
        8.0,
        composition="95% MgO",
        production_process="sintered",
        provider="grade registry",
        declared_product="magnesia",
        boundary_modules=("A1", "A2", "A3"),
        factor_kind=FactorKind.EMISSION_LIMIT,
        metadata={"series_id": "series-limit-test", "grade": "95"},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([base]),
        grade_series=InMemoryGradeSeriesRepository([limit]),
    ).resolve(request(material_name="magnesia 90%", composition="95% MgO", production_process="sintered"))

    assert result.diagnostic_candidates[0].resolution_type == ResolutionType.GRADE_PROXY
    assert any(item["source_id"] == limit.source_id for item in result.trace.explain()["excluded_candidates"])


@pytest.mark.asyncio
async def test_invalid_exact_continues_to_valid_registered_alias():
    invalid_exact = record(
        "invalid-exact-limit",
        "magnesia",
        2.0,
        factor_kind=FactorKind.EMISSION_LIMIT,
    )
    valid_alias = record(
        "valid-magnesia-alias",
        "high purity magnesia",
        1.2,
        metadata={"aliases": '["magnesia"]'},
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([invalid_exact, valid_alias])
    ).resolve(request(material_name="magnesia", composition="carbon steel", quantity_unit="kg"))

    assert result.candidates[0].source.source_id == valid_alias.source_id
    assert result.candidates[0].resolution_type == ResolutionType.DIRECT_ALIAS


@pytest.mark.asyncio
async def test_446_proxy_runs_grade_then_process_resolution():
    base = record(
        "ferritic-base-90",
        "ferritic stainless steel coil 90%",
        1.2,
        unit="tCO2e/t",
        product_form="coil",
        composition="90% Cr",
        production_process="cold rolling",
        declared_product="ferritic stainless steel",
        boundary_modules=("A1", "A2", "A3"),
        metadata={
            "material_category": "METAL",
            "family": "metals",
            "series_id": "ferritic-series",
            "grade": "90",
            "includes_process": "true",
            "resolution_order": "grade,process",
        },
    )
    exact_grade = record(
        "ferritic-anchor-95",
        "ferritic stainless steel coil 95%",
        1.2,
        unit="tCO2e/t",
        product_form="coil",
        composition="95% Cr",
        production_process="cold rolling",
        provider=base.provider,
        declared_product="ferritic stainless steel",
        boundary_modules=("A1", "A2", "A3"),
        metadata={
            "material_category": "METAL",
            "series_id": "ferritic-series",
            "grade": "95",
            "includes_process": "true",
            "resolution_order": "grade,process",
        },
    )
    process = [
        parameter(
            "draw-remove",
            "removed_process_factor",
            0.2,
            "kgCO2e/kg",
            reference_source_id=exact_grade.source_id,
            target_material="446 heat resistant steel fiber",
            target_process="fiber drawing",
        ),
        parameter(
            "draw-add",
            "added_process_factor",
            0.5,
            "kgCO2e/kg",
            reference_source_id=exact_grade.source_id,
            target_material="446 heat resistant steel fiber",
            target_process="fiber drawing",
        ),
    ]
    result = await A1FactorResolutionEngine(
        proxy_retrieval=InMemoryProxyRepository([base]),
        grade_series=InMemoryGradeSeriesRepository([exact_grade]),
        process_parameters=InMemoryProcessParameterRepository(process),
    ).resolve(request(
        material_name="446 heat resistant steel fiber",
        product_form="fiber",
        composition="95% Cr",
        production_process="fiber drawing",
        min_score=0.0,
    ))

    candidate = result.candidates[0]
    assert candidate.origin == CandidateOrigin.PROXY
    assert candidate.resolution_type == ResolutionType.PROCESS_ADJUSTED
    assert candidate.factor_value == pytest.approx(1.5)
    formulas = tuple(step.formula_id for step in candidate.transformation_steps)
    assert "unit.factor_scale/v1" in formulas
    assert "process.delta_adjust/v1" in formulas
    stages = tuple(entry.stage for entry in result.trace.entries)
    assert stages.index("grade_composition_resolution") < stages.index("process_variant_resolution")
    assert candidate.result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS


@pytest.mark.asyncio
async def test_min_score_caps_low_score_candidate_at_reference_only():
    sparse = record(
        "sparse-score",
        "steel coil",
        1.0,
        geography=None,
        year=None,
        product_form=None,
        composition=None,
        production_process="electric arc furnace",
        boundary=None,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sparse])
    ).resolve_debug(request(min_score=0.99))

    assert result.reviewable_candidates[0].score < 0.99
    assert result.reviewable_candidates[0].result_tier == ResultTier.REFERENCE_ONLY


@pytest.mark.asyncio
async def test_unknown_factor_kind_cannot_be_primary():
    unknown = record(
        "unknown-kind",
        "steel coil",
        1.0,
        factor_kind=FactorKind.OTHER,
        indicator=None,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([unknown])
    ).resolve(request())

    assert result.reviewable_candidates[0].result_tier == ResultTier.REFERENCE_ONLY


@pytest.mark.asyncio
async def test_one_tonne_and_1000kg_share_normalized_fingerprint():
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record("fingerprint", "steel coil", 1.0)])
    )
    first = await engine.resolve(request(quantity=1, quantity_unit="t", request_id="fingerprint-tonne"))
    second = await engine.resolve(request(quantity=1000, quantity_unit="kg", request_id="fingerprint-kg"))

    assert first.trace.raw_request_fingerprint != second.trace.raw_request_fingerprint
    assert first.trace.normalized_business_fingerprint == second.trace.normalized_business_fingerprint
    comparison = await engine.compare_traces(first.request_id, second.request_id)
    assert comparison["same_request"] is True


@pytest.mark.asyncio
async def test_duplicate_request_id_cannot_split_trace_and_recommendation():
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record("duplicate", "steel coil", 1.0)])
    )
    first = request(request_id="same-run-id")
    await engine.resolve(first)
    with pytest.raises(ValueError, match="duplicate request_id"):
        await engine.resolve(request(request_id="same-run-id", quantity=2))

    stored = await engine.state("same-run-id")
    trace = await engine.trace("same-run-id")
    assert stored is not None and trace is not None
    assert stored.trace is trace


@pytest.mark.asyncio
async def test_http_catalog_preserves_original_document_locator_when_supplied():
    digest = "d" * 64
    payload = {
        "catalog_version": "v-provenance",
        "database": {"name": "catalog.db", "sha256": digest},
        "records": [{
                "record_id": "documented-factor",
                "source_quality_status": "VERIFIED",
                "admission_eligible": True,
                "subject_type": "raw_material",
            "name": "steel coil",
            "primary_value": 1.1,
            "primary_unit": "kgCO2e/kg",
            "factor_kind": "lifecycle_factor",
            "indicator": "GWP-total",
            "boundary": "cradle-to-gate",
            "production_process": "electric arc furnace",
            "source_document_locator": "https://example.test/epd.pdf",
            "source_document_sha256": "e" * 64,
            "page": 12,
            "table": "A1-A3",
            "row": 4,
        }],
    }
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: payload,
        )
    ).resolve(request())

    source = result.reviewable_candidates[0].source
    assert source.locator == "https://example.test/epd.pdf"
    assert source.catalog_locator.endswith("#documented-factor")
    assert source.provenance.source_document_sha256 == "e" * 64
    assert (source.page, source.table, source.row) == ("12", "A1-A3", "4")


@pytest.mark.asyncio
async def test_http_catalog_preserves_live_source_path_and_sha_aliases():
    digest = "f" * 64
    payload = {
        "catalog_version": "v-live-aliases",
        "database": {"name": "catalog.db", "sha256": digest},
        "records": [{
                "record_id": "live-source-aliases",
                "source_quality_status": "VERIFIED",
                "admission_eligible": True,
                "subject_type": "raw_material",
            "name": "steel coil",
            "primary_value": 1.2,
            "primary_unit": "kgCO2e/kg",
            "category": "lifecycle_factor",
            "indicator": "GWP-total",
            "boundary": "cradle-to-gate",
            "production_process": "electric arc furnace",
            "source_path": "fixture-evidence/standard.pdf",
            "source_sha256": "a" * 64,
            "primary_label": "产品碳足迹因子",
            "scope": "raw_material",
            "source_version": "draft-v1",
            "upstream_source_status": "AGGREGATED",
            "includes_process": True,
        }],
    }
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: payload,
        )
    ).resolve(request())

    source = result.reviewable_candidates[0].source
    assert source.locator == "fixture-evidence/standard.pdf"
    assert source.provenance.source_document_sha256 == "a" * 64
    assert source.metadata["primary_label"] == "产品碳足迹因子"
    assert source.metadata["includes_process"] == "True"


@pytest.mark.asyncio
async def test_refractory_catalog_policy_inherits_only_reviewed_dataset_fields():
    digest = "b" * 64
    payload = {
        "catalog_version": "formal-refractory-v1",
        "database": {"name": "emission_factors.db", "sha256": digest},
        "records": [{
                "record_id": "refractory-standard:sintered-spinel",
                "source_quality_status": "VERIFIED",
                "admission_eligible": True,
                "subject_type": "raw_material",
            "category": "lifecycle_factor",
            "name": "烧结尖晶石",
            "primary_value": 4.602431,
            "primary_unit": "kgCO2e/kg",
            "source": "温室气体 产品碳足迹量化方法与要求 耐火材料",
            "primary_label": "产品碳足迹因子",
            "standard": "GB/T XXXX-202X 征求意见稿",
            "scope": "raw_material",
            "production_process": "sintered",
            "source_document_locator": "https://example.invalid/refractory/sintered-spinel",
            "source_document_sha256": "2" * 64,
        }],
    }
    content_digest = catalog_content_sha256(payload["records"])
    policy = CatalogDatasetPolicy(
        policy_id="deployment.refractory-a1-product-carbon-footprint/v1",
        record_categories=("lifecycle_factor",),
        standards=("GB/T XXXX-202X 征求意见稿",),
        primary_labels=("产品碳足迹因子",),
        indicator="GWP-total",
        boundary="cradle-to-gate",
        declared_product_from_name=True,
        evidence_citation="reviewed synthetic deployment policy",
        production_approval_id="deployment-approval:refractory-a1/v1",
        source_priority_rank=0,
        catalog_content_sha256=content_digest,
    )
    bundle = CatalogPolicyBundle(
        policy_id="deployment-policy:refractory/v1",
        version="1",
        approved_catalog_content_sha256=content_digest,
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(policy,),
        signature="test-signature",
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: payload,
            policy_bundle=bundle,
            policy_signature_verifier=lambda _payload, _signature: True,
            policy_effective_on="2026-09-04",
        )
    ).resolve(ResolutionRequest(
        material_name="烧结尖晶石",
        quantity=1,
        production_process="sintered",
        boundary="cradle-to-gate",
    ))

    source = result.candidates[0].source
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].result_tier == ResultTier.PRIMARY_RECOMMENDATION
    assert source.indicator == "GWP-total"
    assert source.declared_product == "烧结尖晶石"
    assert source.boundary == "cradle-to-gate"
    assert source.year is None
    assert source.geography is None
    assert json.loads(source.metadata["catalog_dataset_policy_ids"]) == [
        "deployment.refractory-a1-product-carbon-footprint/v1"
    ]
    assert set(json.loads(source.metadata["catalog_inherited_fields"])) == {
        "indicator", "boundary", "declared_product",
    }
    assert json.loads(source.metadata["result_tier_cap_reasons"]) == [
        "draft_or_consultation"
    ]
    assert json.loads(source.metadata["catalog_dataset_approval_ids"]) == [
        "deployment-approval:refractory-a1/v1"
    ]
    assert source.metadata["source_priority_rank"] == "0"
    assert source.metadata["catalog_policy_bundle_signature_status"] == "verified"


@pytest.mark.asyncio
async def test_customer_source_priority_applies_after_candidate_eligibility():
    common = {
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "geography": "CN",
        "year": 2024,
        "boundary": "cradle-to-gate",
    }
    records = (
        record("ecoinvent-312", "steel coil", 1.0, **common,
               metadata={"source_priority_rank": "20"}),
        record("draft", "steel coil", 1.0, **common,
               metadata={"source_priority_rank": "0"}),
        record("ecoinvent-310", "steel coil", 1.0, **common,
               metadata={"source_priority_rank": "10"}),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(records)
    ).resolve(request(top_k=3))

    assert [item.source.source_id for item in result.candidates] == [
        "draft", "ecoinvent-310", "ecoinvent-312"
    ]


@pytest.mark.asyncio
async def test_soft_reference_coexists_with_primary_in_separate_unapprovable_channel():
    primary = record("primary", "steel coil", 1.0)
    soft = record(
        "soft-reference", "steel coil", 0.8,
        factor_kind=FactorKind.OTHER, indicator=None,
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([soft, primary])
    )
    result = await engine.resolve(request(top_k=2))

    assert [item.source.source_id for item in result.candidates] == ["primary"]
    assert [item.source.source_id for item in result.reviewable_candidates] == [
        "soft-reference"
    ]
    assert result.diagnostic_candidates == ()
    review_id = result.reviewable_candidates[0].candidate_id
    assert result.reviewable_candidate_reasons[review_id] == (
        "reference_only_candidate_requires_explicit_review",
    )
    with pytest.raises(ValueError, match="cannot enter ordinary approval"):
        await engine.approve(result.request_id, review_id, "reviewer")
    approval = await engine.approve(
        result.request_id,
        review_id,
        "reviewer",
        "reference retained for comparison",
        ApprovalMode.REFERENCE_OVERRIDE,
    )
    assert approval.mode == ApprovalMode.REFERENCE_OVERRIDE
    assert review_id in result.trace.latest("top_k").details["reviewable_candidate_ids"]


@pytest.mark.asyncio
async def test_reviewable_only_is_not_reported_as_unresolved():
    soft = record(
        "soft-reference-only", "steel coil", 0.8,
        factor_kind=FactorKind.OTHER, indicator=None,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([soft])
    ).resolve(request())

    assert result.status == ResolutionStatus.REFERENCE_REVIEW_REQUIRED
    assert result.reviewable_candidates
    assert "traceable reference candidate" in result.message
    assert "no traceable candidate" not in result.message
    assert all(
        item["strategy"] != LinkStrategy.UNRESOLVED.value
        for item in result.trace.explain()["link_attempts"]
    )


@pytest.mark.parametrize("invalid_rank", [1.9, True, "10", "first", -1, 1001])
@pytest.mark.asyncio
async def test_malformed_source_priority_isolated_to_record_warning(invalid_rank):
    digest = "9" * 64
    common = {
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "subject_type": "raw_material",
        "name": "steel coil",
        "primary_value": 1.0,
        "primary_unit": "kgCO2e/kg",
        "factor_kind": "lifecycle_factor",
        "indicator": "GWP-total",
        "declared_product": "steel coil",
        "boundary": "cradle-to-gate",
        "boundary_modules": ["A1", "A2", "A3"],
        "production_process": "electric arc furnace",
        "geography": "CN",
        "year": 2024,
        "source_document_locator": "https://example.invalid/priority/steel",
        "source_document_sha256": "3" * 64,
    }
    payload = {
        "catalog_version": "dirty-priority-v1",
        "database": {"name": "catalog.db", "sha256": digest},
        "records": [
            {
                **common,
                "record_id": "dirty-priority",
                "source": "ecoinvent 3.10",
                "source_priority_rank": invalid_rank,
            },
            {
                **common,
                "record_id": "valid-priority",
                "source_priority_rank": 5,
            },
        ],
    }
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest, fetch_json=lambda _: payload
        )
    ).resolve(request(top_k=2))

    assert [item.source.source_id for item in result.reviewable_candidates] == [
        "valid-priority", "dirty-priority"
    ]
    dirty = next(
        item for item in result.reviewable_candidates
        if item.source.source_id == "dirty-priority"
    )
    assert dirty.source.metadata["source_priority_rank"] == "10"
    assert "invalid source_priority_rank=" in dirty.source.metadata["source_priority_issue"]
    ranking = result.trace.latest("rank").details["ranking"]
    dirty_rank = next(item for item in ranking if item["source_id"] == "dirty-priority")
    assert "fell back to inferred rank 10" in dirty_rank["source_priority_issue"]


@pytest.mark.asyncio
async def test_explicit_dataset_approval_anchor_can_lift_draft_tier_cap():
    digest = "c" * 64
    payload = {
        "catalog_version": "approved-refractory-v1",
        "database": {"name": "emission_factors.db", "sha256": digest},
        "records": [{
                "record_id": "approved-draft:sintered-spinel",
                "source_quality_status": "VERIFIED",
                "admission_eligible": True,
                "subject_type": "raw_material",
            "category": "lifecycle_factor",
            "name": "烧结尖晶石",
            "primary_value": 4.602431,
            "primary_unit": "kgCO2e/kg",
            "primary_label": "产品碳足迹因子",
            "standard": "GB/T XXXX-202X 征求意见稿",
            "production_process": "sintered",
            "source_document_locator": "https://example.invalid/approved/sintered-spinel",
            "source_document_sha256": "4" * 64,
        }],
    }
    approved_policy = CatalogDatasetPolicy(
        policy_id="catalog.refractory-a1-approved-for-production/v1",
        record_categories=("lifecycle_factor",),
        standards=("GB/T XXXX-202X 征求意见稿",),
        primary_labels=("产品碳足迹因子",),
        indicator="GWP-total",
        boundary="cradle-to-gate",
        declared_product_from_name=True,
        evidence_citation="reviewed internal dataset approval record",
        production_approval_id="dataset-approval:refractory-a1/v1",
        catalog_content_sha256=catalog_content_sha256(payload["records"]),
    )
    approved_bundle = CatalogPolicyBundle(
        policy_id="deployment-policy:approved-refractory/v1",
        version="1",
        approved_catalog_content_sha256=catalog_content_sha256(payload["records"]),
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(approved_policy,),
        signature="test-signature",
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: payload,
            policy_bundle=approved_bundle,
            policy_signature_verifier=lambda _payload, _signature: True,
            policy_effective_on="2026-09-04",
        )
    ).resolve(ResolutionRequest(
        material_name="烧结尖晶石",
        quantity=1,
        production_process="sintered",
        boundary="cradle-to-gate",
    ))

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].result_tier == ResultTier.PRIMARY_RECOMMENDATION
    assert json.loads(
        result.candidates[0].source.metadata["catalog_dataset_approval_ids"]
    ) == ["dataset-approval:refractory-a1/v1"]


@pytest.mark.asyncio
async def test_reference_flow_question_matches_functional_unit():
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([
            record("volume-factor", "refractory castable", 1.0, product_form="bulk")
        ])
    ).resolve(request(
        material_name="refractory castable",
        quantity=2,
        quantity_unit="m3",
        product_form="bulk",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.trace.explain()["required_fields"] == ("density",)


@pytest.mark.asyncio
async def test_unverified_supplier_label_does_not_outrank_documented_epd():
    supplier = record(
        "supplier-unverified",
        "steel coil",
        1.0,
        source_type=FactorSourceType.SUPPLIER,
        citation="",
        metadata={},
    )
    epd = record(
        "documented-epd",
        "steel coil",
        1.0,
        source_type=FactorSourceType.EPD,
        citation="verified EPD",
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([supplier, epd])
    ).resolve(request())

    assert [candidate.source.source_id for candidate in result.candidates[:2]] == [epd.source_id, supplier.source_id]
