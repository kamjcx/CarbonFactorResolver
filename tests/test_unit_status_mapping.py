from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    FactorKind,
    FactorSourceType,
    ResolutionRequest,
    ResolutionStatus,
    SourceRecord,
)
from a1_factor_engine.adapters import HttpCatalogFactorRepository, InMemoryFactorRepository
from a1_factor_engine.units import UnitConversionEvidence

UNIT_SYNTAX_UNSUPPORTED = "UNIT_SYNTAX_UNSUPPORTED"
CATALOG_FACTOR_UNIT_INVALID = "CATALOG_FACTOR_UNIT_INVALID"
UNIT_DIMENSION_MISMATCH = "UNIT_DIMENSION_MISMATCH"
UNIT_CONVERSION_EVIDENCE_REQUIRED = "UNIT_CONVERSION_EVIDENCE_REQUIRED"


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _reason_codes(value: Any) -> tuple[str, ...]:
    return tuple(str(_value(item)) for item in value.reason_codes)


def _record(
    source_id: str = "steel-valid",
    *,
    factor_unit: str = "kgCO2e/kg",
    factor_value: float = 1.25,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="unit-contract-fixture",
        locator=f"fixture://{source_id}",
        material_name="steel coil",
        factor_value=factor_value,
        factor_unit=factor_unit,
        geography="CN",
        year=2024,
        product_form="coil",
        composition="carbon steel",
        production_process="electric arc furnace",
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        indicator="GWP-total",
        declared_product="steel coil",
    )


def _request(**changes: Any) -> ResolutionRequest:
    values: dict[str, Any] = {
        "request_id": "unit-contract-request",
        "material_name": "steel coil",
        "quantity": 1,
        "quantity_unit": "kg",
        "geography": "CN",
        "year": 2024,
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "boundary": "cradle-to-gate",
    }
    values.update(changes)
    return ResolutionRequest(**values)


def _catalog_record(
    source_id: str,
    unit: str,
    *,
    value: float = 1.25,
) -> dict[str, Any]:
    return {
        "record_id": source_id,
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "subject_type": "unknown",
        "name": "steel coil",
        "primary_value": value,
        "primary_unit": unit,
        "factor_kind": "lifecycle_factor",
        "indicator": "GWP-total",
        "declared_product": "steel coil",
        "boundary": "cradle-to-gate",
        "boundary_modules": ["A1", "A2", "A3"],
        "geography": "CN",
        "year": 2024,
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "source_document_locator": f"https://example.invalid/unit/{source_id}",
        "source_document_sha256": "6" * 64,
    }


def _catalog_engine(*records: dict[str, Any]) -> A1FactorResolutionEngine:
    digest = "9" * 64
    return A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            expected_sha256=digest,
            fetch_json=lambda _: {
                "catalog_version": "unit-contract-fixture/v1",
                "database": {"name": "unit-contract.db", "sha256": digest},
                "records": list(records),
            },
        )
    )


def _assert_terminal(
    result: Any,
    status: ResolutionStatus,
    follow_up: str,
    reason_code: str,
) -> None:
    assert result.status == status
    assert _value(result.follow_up) == follow_up
    assert _reason_codes(result) == (reason_code,)
    assert result.candidates == ()
    assert result.reviewable_candidates == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_changes",
    (
        {"target_factor_unit": "not-a-factor-unit"},
        {"quantity_unit": "not-an-activity-unit", "target_factor_unit": None},
    ),
    ids=("target-factor-unit", "activity-quantity-unit"),
)
async def test_request_unit_syntax_is_unresolved_not_supplier_data(
    request_changes: dict[str, Any],
) -> None:
    result = await A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([_record()])).resolve(
        _request(**request_changes)
    )

    _assert_terminal(
        result,
        ResolutionStatus.UNRESOLVED,
        "unresolved",
        UNIT_SYNTAX_UNSUPPORTED,
    )
    explanation = result.trace.explain()
    assert UNIT_SYNTAX_UNSUPPORTED in explanation["reason_codes"]


@pytest.mark.asyncio
async def test_invalid_catalog_factor_unit_is_governance_failure_and_never_admitted() -> None:
    result = await _catalog_engine(_catalog_record("catalog-invalid-unit", "kgCO2e/not-a-unit")).resolve(
        _request()
    )

    _assert_terminal(
        result,
        ResolutionStatus.UNRESOLVED,
        "data-governance",
        CATALOG_FACTOR_UNIT_INVALID,
    )
    explanation = result.trace.explain()
    conversion = next(
        item for item in explanation["conversion_diagnostics"] if item["source_id"] == "catalog-invalid-unit"
    )
    qualification = next(
        item
        for item in explanation["qualification_diagnostics"]
        if item["source_id"] == "catalog-invalid-unit" and item["dimension"] == "unit"
    )
    admission = next(
        item for item in explanation["candidate_admissions"] if item["source_id"] == "catalog-invalid-unit"
    )
    exclusion = next(
        item for item in explanation["excluded_candidates"] if item["source_id"] == "catalog-invalid-unit"
    )

    assert conversion["reason_code"] == CATALOG_FACTOR_UNIT_INVALID
    assert qualification["reason_codes"] == (CATALOG_FACTOR_UNIT_INVALID,)
    assert admission["admitted"] is False
    assert admission["observation_only"] is True
    assert CATALOG_FACTOR_UNIT_INVALID in admission["hard_exclusions"]
    assert CATALOG_FACTOR_UNIT_INVALID in exclusion["reasons"]
    assert explanation["reason_codes"] == (CATALOG_FACTOR_UNIT_INVALID,)


@pytest.mark.asyncio
async def test_factor_activity_dimension_mismatch_is_unresolved() -> None:
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([_record(factor_unit="kgCO2e/kg")])
    ).resolve(_request(quantity_unit="kWh", target_factor_unit=None))

    _assert_terminal(
        result,
        ResolutionStatus.UNRESOLVED,
        "unresolved",
        UNIT_DIMENSION_MISMATCH,
    )
    explanation = result.trace.explain()
    unit_diagnostics = tuple(
        item
        for item in explanation["qualification_diagnostics"]
        if item["source_id"] == "steel-valid" and item["dimension"] == "unit"
    )
    assert unit_diagnostics
    assert all(item["reason_codes"] == (UNIT_DIMENSION_MISMATCH,) for item in unit_diagnostics)


@pytest.mark.asyncio
async def test_m3_to_nm3_without_controlled_evidence_requires_more_input() -> None:
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([_record("normal-volume-factor", factor_unit="kgCO2e/Nm3")])
    ).resolve(_request(quantity=10, quantity_unit="m3", target_factor_unit="kgCO2e/m3"))

    _assert_terminal(
        result,
        ResolutionStatus.MORE_INPUT_NEEDED,
        "more-input",
        UNIT_CONVERSION_EVIDENCE_REQUIRED,
    )
    explanation = result.trace.explain()
    assert explanation["required_fields"] == ("unit_conversion_evidence",)
    assert UNIT_CONVERSION_EVIDENCE_REQUIRED in explanation["reason_codes"]


@pytest.mark.asyncio
async def test_m3_to_nm3_with_versioned_controlled_evidence_can_recommend() -> None:
    evidence = UnitConversionEvidence(
        evidence_id="volume-state-conversion-2024",
        version="2024.1",
        source_canonical_unit="Nm3",
        target_canonical_unit="m3",
        multiplier=Decimal("1"),
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([_record("normal-volume-factor", factor_unit="kgCO2e/Nm3")]),
    )

    result = await engine.resolve(
        _request(
            quantity=10,
            quantity_unit="m3",
            target_factor_unit="kgCO2e/m3",
            unit_conversion_evidence=evidence,
        )
    )

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.follow_up is None
    assert _reason_codes(result) == ()
    assert result.candidates
    assert result.candidates[0].factor_unit == "kgCO2e/m3"
    assert result.candidates[0].factor_value == pytest.approx(1.25)
    assert result.candidates[0].total_emissions_kgco2e == pytest.approx(12.5)
    steps = result.trace.explain()["transformation_steps"]
    assert any(evidence.evidence_id in step["parameter_ids"] for step in steps)


@pytest.mark.asyncio
async def test_nm3_request_uses_forward_source_factor_evidence_without_inverse_preconversion() -> None:
    evidence = UnitConversionEvidence(
        evidence_id="ambient-to-normal-volume-2026",
        version="2026.1",
        source_canonical_unit="m3",
        target_canonical_unit="Nm3",
        multiplier=Decimal("1.04"),
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(
            [_record("ambient-volume-factor", factor_unit="kgCO2e/m3", factor_value=2.08)]
        )
    ).resolve(
        _request(
            quantity=10,
            quantity_unit="Nm3",
            target_factor_unit="kgCO2e/Nm3",
            unit_conversion_evidence=evidence,
        )
    )

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert _reason_codes(result) == ()
    assert result.candidates[0].factor_unit == "kgCO2e/Nm3"
    assert result.candidates[0].factor_value == pytest.approx(2.0)
    assert result.candidates[0].total_emissions_kgco2e == pytest.approx(20.0)
    steps = result.trace.explain()["transformation_steps"]
    assert any(evidence.evidence_id in step["parameter_ids"] for step in steps)


@pytest.mark.asyncio
async def test_true_zero_hit_remains_supplier_data_required() -> None:
    result = await A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([])).resolve(_request())

    assert result.status == ResolutionStatus.SUPPLIER_DATA_REQUIRED
    assert _value(result.follow_up) == "supplier-data"
    assert _reason_codes(result) == ()
    assert result.trace.explain()["reason_codes"] == ()


@pytest.mark.asyncio
async def test_invalid_catalog_unit_is_diagnostic_only_when_an_alternative_is_usable() -> None:
    result = await _catalog_engine(
        _catalog_record("catalog-invalid-unit", "kgCO2e/not-a-unit"),
        _catalog_record("catalog-valid-unit", "kgCO2e/kg"),
    ).resolve(_request())

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.follow_up is None
    assert _reason_codes(result) == (CATALOG_FACTOR_UNIT_INVALID,)
    assert [item.source.source_id for item in result.candidates] == ["catalog-valid-unit"]
    explanation = result.trace.explain()
    assert CATALOG_FACTOR_UNIT_INVALID in explanation["reason_codes"]
    invalid_admission = next(
        item for item in explanation["candidate_admissions"] if item["source_id"] == "catalog-invalid-unit"
    )
    assert invalid_admission["admitted"] is False
    assert CATALOG_FACTOR_UNIT_INVALID in invalid_admission["hard_exclusions"]


def test_unit_reason_fields_are_serialized_by_all_resolution_api_surfaces() -> None:
    fastapi = pytest.importorskip("fastapi")
    assert fastapi is not None
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    request_id = "unit-api-contract"
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([_record()]))
    payload = {
        "request_id": request_id,
        "material_name": "steel coil",
        "quantity": 1,
        "quantity_unit": "kWh",
        "geography": "CN",
        "year": 2024,
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "boundary": "cradle-to-gate",
    }

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "tester", "tenant", "project",
            ("resolve:execute", "resolution:read", "trace:read", "diagnostics:read"),
        )
    with TestClient(create_admin_app(engine=engine, authorizer=allow)) as client:
        posted = client.post("/api/v1/resolve", json=payload)
        assert posted.status_code == 200
        resolution = client.get(f"/api/v1/resolutions/{request_id}")
        trace = client.get(f"/api/v1/traces/{request_id}")
        diagnostics = client.get(f"/api/v1/diagnostics/{request_id}")

    for response in (resolution, trace, diagnostics):
        assert response.status_code == 200

    posted_payload = posted.json()
    resolution_payload = resolution.json()
    trace_payload = trace.json()
    diagnostics_payload = diagnostics.json()
    for item in (posted_payload, resolution_payload):
        assert item["status"] == "unresolved"
        assert item["follow_up"] == "unresolved"
        assert item["reason_codes"] == [UNIT_DIMENSION_MISMATCH]
    assert trace_payload["reason_codes"] == [UNIT_DIMENSION_MISMATCH]
    assert diagnostics_payload["status"] == "unresolved"
    assert diagnostics_payload["follow_up"] == "unresolved"
    assert diagnostics_payload["reason_codes"] == [UNIT_DIMENSION_MISMATCH]
    assert diagnostics_payload["required_fields"] == []
    assert isinstance(diagnostics_payload["qualification_diagnostics"], list)
    assert isinstance(diagnostics_payload["conversion_diagnostics"], list)
    unit_diagnostics = [
        item
        for item in diagnostics_payload["qualification_diagnostics"]
        if item["source_id"] == "steel-valid" and item["dimension"] == "unit"
    ]
    assert unit_diagnostics
    assert all(item["reason_codes"] == [UNIT_DIMENSION_MISMATCH] for item in unit_diagnostics)
