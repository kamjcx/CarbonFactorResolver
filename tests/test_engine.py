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
    ParameterEvidence,
    ParameterSourceType,
    ReferenceFlowRecord,
    ResolutionRequest,
    ResolutionStatus,
    ResolutionType,
    ResultTier,
    SourceRecord,
)
from a1_factor_engine.adapters import (
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
    InMemoryGradeSeriesRepository,
    InMemoryProcessParameterRepository,
    InMemoryProxyRepository,
    InMemoryReferenceFlowRepository,
)
from a1_factor_engine.units import convert_factor, convert_mass, parse_factor_unit


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
        factor_kind=kwargs.pop("factor_kind", FactorKind.OTHER),
        indicator=kwargs.pop("indicator", None),
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
    assert attempts[1]["outcome"] == LinkOutcome.SKIPPED.value


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
    evidence = [parameter(*item, reference_source_id="sintered-mullite", target_material="electrofused mullite") for item in values]
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
        metadata={"series": "sintered magnesia", "grade": "90"},
    )
    grade_97 = record(
        "magnesia-97", "magnesia 97", 1.7, composition="97% MgO",
        production_process="sintered", provider="series provider",
        metadata={"series": "sintered magnesia", "grade": "97"},
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
        parameter("remove", "removed_process_factor", 0.4, "kgCO2e/kg", reference_source_id="raw-upstream", target_material="fused alumina"),
        parameter("add", "added_process_factor", 0.7, "kgCO2e/kg", reference_source_id="raw-upstream", target_material="fused alumina"),
    ]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source]),
        process_parameters=InMemoryProcessParameterRepository(evidence),
    ).resolve(request(material_name="fused alumina", production_process="fused"))

    candidate = result.candidates[0]
    assert candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY
    assert candidate.factor_value == 2.0
    assert any("does not include" in warning for warning in candidate.warnings)


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
