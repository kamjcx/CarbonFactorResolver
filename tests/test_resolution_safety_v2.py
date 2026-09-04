from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    DeploymentPolicy,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    ParameterEvidence,
    ParameterSourceType,
    ReferenceFlowRecord,
    ResolutionRequest,
    ResolutionStatus,
    ResultTier,
    SourceRecord,
)
from a1_factor_engine.adapters import (
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
    InMemoryReferenceFlowRepository,
)
from a1_factor_engine.units import parse_activity_unit, parse_factor_unit


def source(source_id: str, name: str, **changes) -> SourceRecord:
    values = dict(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="public synthetic",
        locator=f"evidence://{source_id}",
        material_name=name,
        factor_value=1.0,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2024,
        product_form=None,
        composition=None,
        production_process=None,
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        indicator="GWP-total",
        declared_product=name,
        boundary_modules=("A1", "A2", "A3"),
    )
    values.update(changes)
    return SourceRecord(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "request_value", "source_value", "reason"),
    (("geography", "CN", "US", "geography_mismatch"), ("year", 2024, 2019, "year_mismatch")),
)
async def test_explicit_geography_and_year_conflicts_never_escape(
    field: str, request_value: object, source_value: object, reason: str
) -> None:
    record = source("conflict", "synthetic alumina", **{field: source_value})
    request = ResolutionRequest(
        material_name="synthetic alumina", quantity=1, subject_type=FactorSubjectType.RAW_MATERIAL,
        geography="CN", year=2024,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record])
    ).resolve(replace(request, **{field: request_value}))

    assert result.candidates == ()
    assert reason in {
        item for excluded in result.trace.explain()["excluded_candidates"]
        for item in excluded["reasons"]
    }


@pytest.mark.asyncio
async def test_versioned_substitution_policy_is_explicit_and_auditable() -> None:
    record = source(
        "substitution", "synthetic alumina", geography="US",
        metadata={
            "substitution_policy_id": "geo-substitution-public-synthetic",
            "substitution_policy_version": "1",
            "substitution_dimensions": "geography",
        },
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record])
    ).resolve(ResolutionRequest(
        material_name="synthetic alumina", quantity=1,
        subject_type=FactorSubjectType.RAW_MATERIAL, geography="CN", year=2024,
    ))

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    checks = result.trace.explain()["record_qualifications"][0]["policy_checks"]
    assert "versioned geography substitution" in checks["geography"]["reasons"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("boundary", "declared_product"))
async def test_missing_boundary_or_declared_product_is_reference_only_and_unapprovable(
    missing: str,
) -> None:
    record = source("incomplete", "synthetic alumina")
    record = replace(
        record,
        **({"boundary": None, "boundary_modules": ()} if missing == "boundary" else {"declared_product": None}),
    )
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([record]))
    result = await engine.resolve(ResolutionRequest(
        material_name="synthetic alumina", quantity=1,
        subject_type=FactorSubjectType.RAW_MATERIAL, geography="CN", year=2024,
    ))

    assert result.candidates == ()
    assert result.reviewable_candidates[0].result_tier == ResultTier.REFERENCE_ONLY
    with pytest.raises(ValueError, match="mandatory formal evidence"):
        await engine.approve(
            result.request_id, result.reviewable_candidates[0].candidate_id,
            "reviewer", "cannot cure absent evidence", ApprovalMode.REFERENCE_OVERRIDE,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "unit", "factor_unit", "subject", "kind", "quantity", "expected"),
    (
        ("synthetic electricity", "kWh", "kgCO2e/kWh", FactorSubjectType.ENERGY, FactorKind.ENERGY_FACTOR, 12, 6),
        ("synthetic road freight", "tkm", "kgCO2e/(t*km)", FactorSubjectType.TRANSPORT, FactorKind.TRANSPORT_FACTOR, 100, 7.8),
        ("synthetic process gas", "m3", "kgCO2e/m3", FactorSubjectType.PROCESS, FactorKind.LIFECYCLE_FACTOR, 4, 8),
    ),
)
async def test_non_mass_candidates_recompute_total_at_lock(
    name: str, unit: str, factor_unit: str, subject: FactorSubjectType,
    kind: FactorKind, quantity: float, expected: float,
) -> None:
    factor = expected / quantity
    record = source(
        "operational", name, factor_value=factor, factor_unit=factor_unit,
        subject_type=subject, factor_kind=kind,
    )
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([record]))
    result = await engine.resolve(ResolutionRequest(
        material_name=name, quantity=quantity, quantity_unit=unit,
        target_factor_unit=factor_unit, subject_type=subject, geography="CN", year=2024,
    ))
    candidate = result.candidates[0]
    assert candidate.resolved_activity_value == pytest.approx(quantity)
    assert candidate.total_emissions_kgco2e == pytest.approx(expected)
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    assert locked.candidate.total_emissions_kgco2e == pytest.approx(expected)


@pytest.mark.asyncio
async def test_non_mass_lock_rejects_a_tampered_total() -> None:
    record = source(
        "tamper-energy", "tamper electricity", factor_value=0.5,
        factor_unit="kgCO2e/kWh", subject_type=FactorSubjectType.ENERGY,
        factor_kind=FactorKind.ENERGY_FACTOR,
    )
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([record]))
    result = await engine.resolve(ResolutionRequest(
        material_name="tamper electricity", quantity=10, quantity_unit="kWh",
        target_factor_unit="kgCO2e/kWh", subject_type=FactorSubjectType.ENERGY,
        geography="CN", year=2024,
    ))
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    engine.store.recommendations[result.request_id] = replace(
        result, candidates=(replace(candidate, total_emissions_kgco2e=999),)
    )
    with pytest.raises(ValueError, match="total emissions are inconsistent"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
@pytest.mark.parametrize("material_name", ("steel fibre", "钢纤维", "steel fiber"))
async def test_broad_steel_fibre_is_more_input_with_non_selectable_steel_reference(
    material_name: str,
) -> None:
    record = source("generic-steel", "steel")
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([record])
    )
    result = await engine.resolve(ResolutionRequest(
        material_name=material_name,
        quantity=1,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        boundary="cradle-to-gate",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.candidates == ()
    assert [item.source.source_id for item in result.reviewable_candidates] == [
        "generic-steel"
    ]
    assert result.reviewable_candidates[0].result_tier == ResultTier.REFERENCE_ONLY
    assert result.trace.explain()["required_choice"]["field"] == "steel_fiber_type"
    with pytest.raises(ValueError, match="recommendation-ready or reference-review"):
        await engine.approve(
            result.request_id,
            result.reviewable_candidates[0].candidate_id,
            "reviewer",
        )


@pytest.mark.asyncio
async def test_reference_flow_rejects_wrong_packaging_before_arithmetic() -> None:
    evidence = ParameterEvidence(
        "roll-mass", "mass_per_roll", 5, "kg/roll",
        ParameterSourceType.FORMAL_STANDARD, "synthetic", "evidence://roll",
    )
    flow = ReferenceFlowRecord(
        "wrong-package", "synthetic sheet", "roll", 5, evidence,
    )
    class UntrustedReferenceFlowRepository:
        async def search(self, _activity):
            return (flow,)

    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([
            source("sheet", "synthetic sheet", product_form="sheet")
        ]),
        reference_flows=UntrustedReferenceFlowRepository(),
    ).resolve(ResolutionRequest(
        material_name="synthetic sheet", quantity=2, quantity_unit="piece",
        product_form="sheet", subject_type=FactorSubjectType.RAW_MATERIAL,
        geography="CN", year=2024,
    ))
    assert result.candidates == ()


def test_unit_contract_reaches_area_roll_and_transport_work_syntax() -> None:
    assert parse_activity_unit("m²").canonical_unit == "m2"
    assert parse_activity_unit("roll").canonical_unit == "item"
    assert parse_factor_unit("kgCO2e/(t*km)").activity_unit.canonical_unit == "tkm"


@pytest.mark.asyncio
async def test_area_and_roll_units_are_reachable_end_to_end() -> None:
    area = source(
        "area", "synthetic membrane", factor_value=2,
        factor_unit="kgCO2e/m²", product_form="sheet",
    )
    area_result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([area])
    ).resolve(ResolutionRequest(
        material_name="synthetic membrane", quantity=3, quantity_unit="m²",
        target_factor_unit="kgCO2e/m²", product_form="sheet",
        subject_type=FactorSubjectType.RAW_MATERIAL, geography="CN", year=2024,
    ))
    assert area_result.candidates[0].total_emissions_kgco2e == pytest.approx(6)

    evidence = ParameterEvidence(
        "roll-mass-ok", "mass_per_roll", 5, "kg/roll",
        ParameterSourceType.FORMAL_STANDARD, "synthetic", "evidence://roll-ok",
    )
    flow = ReferenceFlowRecord(
        "roll-ok", "synthetic roll material", "roll", 5, evidence,
    )
    roll_result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([
            source("roll-factor", "synthetic roll material", factor_value=0.5)
        ]),
        reference_flows=InMemoryReferenceFlowRepository([flow]),
    ).resolve(ResolutionRequest(
        material_name="synthetic roll material", quantity=2, quantity_unit="roll",
        subject_type=FactorSubjectType.RAW_MATERIAL, geography="CN", year=2024,
    ))
    assert roll_result.candidates[0].resolved_activity_unit == "kg"
    assert roll_result.candidates[0].total_emissions_kgco2e == pytest.approx(5)


@pytest.mark.asyncio
async def test_catalog_numeric_zero_is_not_parsed_as_missing() -> None:
    digest = "ab" * 32
    repository = HttpCatalogFactorRepository(
        expected_sha256=digest,
        fetch_json=lambda _endpoint: {
            "catalog_version": "zero/v1",
            "database": {"name": "synthetic", "sha256": digest},
            "records": [{
                "record_id": "zero-factor", "name": "synthetic recycled input",
                "primary_value": 0, "primary_unit": "kgCO2e/kg",
                "factor_kind": "lifecycle_factor", "subject_type": "raw_material",
                "source_quality_status": "VERIFIED", "admission_eligible": True,
                "indicator": "GWP-total", "declared_product": "synthetic recycled input",
                "boundary": "cradle-to-gate", "boundary_modules": ["A1", "A2", "A3"],
                "source_document_locator": "evidence://zero", "source_document_sha256": "cd" * 32,
                "geography": "CN", "year": 2024,
            }],
        },
    )
    result = await A1FactorResolutionEngine(local_retrieval=repository).resolve(
        ResolutionRequest(
            material_name="synthetic recycled input", quantity=1,
            subject_type=FactorSubjectType.RAW_MATERIAL, geography="CN", year=2024,
        )
    )
    assert result.candidates[0].factor_value == 0
    assert result.candidates[0].total_emissions_kgco2e == 0


def test_formal_mapping_cannot_override_deployment_threshold() -> None:
    with pytest.raises(ValueError, match="deployment policy"):
        ResolutionRequest.from_mapping({
            "material_name": "synthetic alumina", "quantity": 1, "min_score": 0,
        })
    debug = ResolutionRequest.from_mapping(
        {"material_name": "synthetic alumina", "quantity": 1, "min_score": 0},
        allow_debug_controls=True,
    )
    assert debug.min_score == 0
    assert DeploymentPolicy().min_score == 0.65


def test_formal_http_contract_rejects_min_score_and_debug_route_is_opt_in() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app, create_app

    payload = {"material_name": "synthetic alumina", "quantity": 1, "min_score": 0}
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/resolve", json=payload)
        assert response.status_code == 400
        assert client.post("/api/v1/debug/resolve", json=payload).status_code == 404

    async def allow(_headers, _permission):
        return AuthorizationContext("tester", "tenant", "project", ("resolve:debug",))
    with TestClient(create_admin_app(authorizer=allow)) as client:
        response = client.post("/api/v1/debug/resolve", json=payload)
        assert response.status_code < 500


def test_missing_api_extra_is_an_operational_error_not_an_extra_case(monkeypatch) -> None:
    import builtins

    from tools.autonomous_evaluation.runner import _api_safety_rows

    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "fastapi.testclient":
            raise ImportError("simulated missing optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(RuntimeError, match="must not change the benchmark case inventory"):
        _api_safety_rows()


def test_safety_v2_adjudications_are_case_input_and_runtime_sha_bound() -> None:
    from tools.autonomous_evaluation.contracts import sha256_json
    from tools.autonomous_evaluation.generator import generate_bundle

    path = Path("data/benchmarks/resolution_safety_v2_adjudications.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = {case.case_id: case for case in generate_bundle().cases}
    for entry in payload["entries"]:
        case = cases[entry["case_id"]]
        assert entry["case_sha256"] == case.semantic_fingerprint
        assert entry["input_sha256"] == sha256_json(dict(case.request))
    for source_path, expected in payload["runtime_source_sha256"].items():
        # Text-mode reading normalizes CRLF/LF so the audit binding identifies
        # source content rather than a checkout's platform-specific line endings.
        canonical = Path(source_path).read_text(encoding="utf-8").encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == expected
