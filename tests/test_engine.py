from __future__ import annotations

import json

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    CandidateOrigin,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    GapType,
    LinkOutcome,
    LinkStrategy,
    MaterialCategory,
    MaterialRule,
    ParameterEvidence,
    ParameterSourceType,
    ReferenceFlowRecord,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    ResolutionRequest,
    ResolutionStatus,
    ResolutionType,
    ResultTier,
    SourceRecord,
    VersionedMaterialSemanticRegistry,
)
from a1_factor_engine.adapters import (
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
    InMemoryGradeSeriesRepository,
    InMemoryProcessParameterRepository,
    InMemoryProxyRepository,
    InMemoryReferenceFlowRepository,
)
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.units import convert_factor, convert_mass, parse_factor_unit


def test_versioned_registry_resolves_mullite_spinel_process_and_relations():
    mullite = DEFAULT_MATERIAL_REGISTRY.resolve("电熔莫来石")
    assert mullite.identity.head_material == "mullite"
    assert mullite.identity.material_family == "mullite_products"
    assert mullite.identity.category == MaterialCategory.MANUFACTURED_MINERAL
    assert mullite.identity.manufacturing_route == ("electrofused",)
    assert mullite.material_rule_ids == ("material.mullite/v1",)
    assert mullite.process_rule_ids == ("process.electrofused/v1",)
    assert mullite.relation_ids == ("relation.mullite-is-aluminosilicate/v1",)

    spinel = DEFAULT_MATERIAL_REGISTRY.resolve("烧结尖晶石")
    assert spinel.identity.head_material == "spinel"
    assert spinel.identity.manufacturing_route == ("sintered",)


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
    assert result.candidates
    assert result.candidates[0].source.source_id == "mullite-sintered"
    assert result.candidates[0].source.production_process == "sintered"
    assert any(gap.gap_type == GapType.PROCESS_VARIANT for gap in result.candidates[0].gaps)
    assert not any(gap.gap_type == GapType.MATERIAL_ABSENT for gap in result.candidates[0].gaps)
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
        declared_product=kwargs.pop("declared_product", None),
        boundary_modules=kwargs.pop("boundary_modules", ()),
        metadata=kwargs.pop("metadata", kwargs),
    )


def request(**changes) -> ResolutionRequest:
    values = dict(
        material_name="steel coil",
        quantity=1,
        quantity_unit="t",
        geography="CN",
        year=2024,
        product_form="coil",
        composition="carbon steel",
        production_process="electric arc furnace",
        boundary="cradle-to-gate",
    )
    values.update(changes)
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
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert [c.source.source_id for c in result.candidates] == ["good-process", "bad-process"]
    assert result.candidates[1].resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert result.candidates[1].result_tier == ResultTier.REFERENCE_ONLY
    assert any(gap.gap_type == GapType.PROCESS_VARIANT for gap in result.candidates[1].gaps)


def test_deterministic_unit_conversion():
    assert convert_mass(1, "t", "kg") == 1000
    assert convert_factor(1000, "kgCO2e/t", "kgCO2e/kg") == 1
    assert convert_factor(1000, "gCO2e/kg", "kgCO2e/kg") == 1


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

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert trace is result.trace
    assert trace is not None and trace.database_anchor == anchor
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
async def test_exact_link_stops_before_registered_synonym_link():
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
    assert [candidate.source.source_id for candidate in result.candidates] == ["exact"]
    assert attempts[0]["strategy"] == LinkStrategy.EXACT.value
    assert attempts[0]["outcome"] == LinkOutcome.MATCHED.value
    assert attempts[1]["strategy"] == LinkStrategy.SYNONYM.value
    assert attempts[1]["outcome"] == LinkOutcome.MATCHED.value
    assert "pending exact-record qualification" in attempts[1]["reason"]


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

    assert result.candidates[0].resolution_type == ResolutionType.CLASS_GENERIC_PROXY
    assert result.candidates[0].result_tier == ResultTier.REFERENCE_ONLY
    assert any(gap.gap_type == GapType.MATERIAL_ABSENT for gap in result.candidates[0].gaps)
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

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert candidate.factor_value == 4.0
    assert not any(step.router_type.value == "PROCESS_VARIANT_RESOLUTION" for step in candidate.transformation_steps)


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

    candidate = result.candidates[0]
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
    assert result.candidates[0].resolved_quantity_kg == 50
    assert result.candidates[0].resolution_type == ResolutionType.GRADE_PROXY
    assert any(step.formula_id == "reference_flow.mass_per_piece/v1" for step in result.candidates[0].transformation_steps)


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

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert candidate.factor_value == 2.0
    assert any("includes it" in warning for warning in candidate.warnings)


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
    observations = result.trace.explain()["raw_related_hits"]
    assert observations and observations[-1]["eligible_for_candidate_pool"] is False
    assert observations[-1]["primary_exclusion"] == "material_category_mismatch"
    assert observations[-1]["retrieval_basis"] == ("product form matched: fiber",)
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
    candidate = result.candidates[0]
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
    candidate = result.candidates[0]
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

    assert result.candidates[0].resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert any("negative common upstream" in warning for warning in result.candidates[0].warnings)


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

    assert result.candidates[0].resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert any("target process energy shares must sum to one" in warning for warning in result.candidates[0].warnings)


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

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert candidate.parameter_evidence_ids == ()


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

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert any("explicit evidence" in warning for warning in candidate.warnings)


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

    assert result.candidates[0].resolution_type == ResolutionType.GRADE_PROXY
    assert result.candidates[0].factor_value == pytest.approx(1.0)


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

    assert result.candidates[0].resolution_type == ResolutionType.GRADE_PROXY
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
        production_process=None,
        boundary=None,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([sparse])
    ).resolve(request(min_score=0.99))

    assert result.candidates[0].score < 0.99
    assert result.candidates[0].result_tier == ResultTier.REFERENCE_ONLY


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

    assert result.candidates[0].result_tier == ResultTier.REFERENCE_ONLY


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
            "name": "steel coil",
            "primary_value": 1.1,
            "primary_unit": "kgCO2e/kg",
            "factor_kind": "lifecycle_factor",
            "indicator": "GWP-total",
            "boundary": "cradle-to-gate",
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

    source = result.candidates[0].source
    assert source.locator == "https://example.test/epd.pdf"
    assert source.catalog_locator.endswith("#documented-factor")
    assert source.provenance.source_document_sha256 == "e" * 64
    assert (source.page, source.table, source.row) == ("12", "A1-A3", "4")


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
