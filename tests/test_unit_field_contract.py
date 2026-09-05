from __future__ import annotations

from dataclasses import replace

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    ResolutionRequest,
    SourceRecord,
)
from a1_factor_engine.adapters import (
    InMemoryFactorRepository,
    InMemoryReferenceFlowRepository,
)
from a1_factor_engine.derived_factor import derive_candidate, expected_total_emissions
from a1_factor_engine.models import (
    Candidate,
    CandidateOrigin,
    NormalizedActivity,
    ParameterEvidence,
    ParameterSourceType,
    ReferenceFlowRecord,
    ResolutionType,
)
from a1_factor_engine.nodes import _candidate
from a1_factor_engine.units import ActivityDimension, convert_activity_decimal


def _source(
    factor_unit: str,
    factor_value: float,
    *,
    source_id: str = "unit-field-source",
    subject_type: FactorSubjectType = FactorSubjectType.RAW_MATERIAL,
    factor_kind: FactorKind = FactorKind.LIFECYCLE_FACTOR,
    boundary: str = "cradle-to-gate",
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="PUBLIC_SYNTHETIC",
        locator=f"evidence://{source_id}",
        material_name="unit field material",
        factor_value=factor_value,
        factor_unit=factor_unit,
        geography="CN",
        year=2025,
        boundary=boundary,
        boundary_modules=("A1", "A2", "A3") if boundary == "cradle-to-gate" else (boundary,),
        factor_kind=factor_kind,
        subject_type=subject_type,
        indicator="GWP-total",
        declared_product="unit field material",
        source_document_sha256="ab" * 32,
    )


def _activity(
    quantity: float,
    quantity_unit: str,
    factor_unit: str,
    *,
    dimension: ActivityDimension = ActivityDimension.MASS,
) -> NormalizedActivity:
    quantity_kg = (
        float(convert_activity_decimal(quantity, quantity_unit, "kg"))
        if dimension == ActivityDimension.MASS
        else None
    )
    return NormalizedActivity(
        request_id=f"unit-field-{quantity_unit}-{factor_unit}",
        canonical_name="unit field material",
        aliases=(),
        quantity_kg=quantity_kg,
        geography="CN",
        year=2025,
        product_form=None,
        composition=None,
        production_process=None,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        boundary="cradle-to-gate",
        target_factor_unit=factor_unit,
        original_quantity=quantity,
        original_quantity_unit=quantity_unit,
        quantity_base=quantity_kg if quantity_kg is not None else quantity,
        quantity_base_unit="kg" if quantity_kg is not None else quantity_unit,
        activity_dimension=dimension.value,
    )


@pytest.mark.parametrize(
    ("quantity", "quantity_unit"),
    ((1_000_000, "g"), (1_000, "kg"), (1, "t")),
)
@pytest.mark.parametrize(
    ("factor_value", "factor_unit", "expected_activity"),
    (
        (0.002, "kgCO2e/g", 1_000_000),
        (2.0, "kgCO2e/kg", 1_000),
        (2_000.0, "kgCO2e/t", 1),
    ),
)
def test_mass_application_matrix_keeps_activity_aligned_and_kg_strict(
    quantity: float,
    quantity_unit: str,
    factor_value: float,
    factor_unit: str,
    expected_activity: float,
) -> None:
    candidate, error = _candidate(
        _activity(quantity, quantity_unit, factor_unit),
        _source(factor_unit, factor_value),
        CandidateOrigin.LOCAL,
    )

    assert error is None
    assert candidate is not None
    assert candidate.resolved_activity_value == pytest.approx(expected_activity)
    assert candidate.resolved_activity_unit == factor_unit.rsplit("/", 1)[1]
    assert candidate.resolved_quantity_kg == pytest.approx(1_000)
    assert candidate.total_emissions_kgco2e == pytest.approx(2_000)
    assert expected_total_emissions(candidate) == pytest.approx(2_000)


@pytest.mark.parametrize(
    ("quantity_unit", "factor_unit", "factor_value", "dimension"),
    (
        ("kWh", "kgCO2e/kWh", 0.5, ActivityDimension.ENERGY),
        ("tkm", "kgCO2e/tkm", 0.078, ActivityDimension.TRANSPORT_WORK),
        ("m3", "kgCO2e/m3", 1.2, ActivityDimension.VOLUME),
    ),
)
def test_non_mass_activity_never_populates_resolved_quantity_kg(
    quantity_unit: str,
    factor_unit: str,
    factor_value: float,
    dimension: ActivityDimension,
) -> None:
    activity = _activity(10, quantity_unit, factor_unit, dimension=dimension)
    source = _source(
        factor_unit,
        factor_value,
        subject_type=(
            FactorSubjectType.ENERGY
            if dimension == ActivityDimension.ENERGY
            else FactorSubjectType.TRANSPORT
            if dimension == ActivityDimension.TRANSPORT_WORK
            else FactorSubjectType.PROCESS
        ),
        factor_kind=(
            FactorKind.ENERGY_FACTOR
            if dimension == ActivityDimension.ENERGY
            else FactorKind.TRANSPORT_FACTOR
            if dimension == ActivityDimension.TRANSPORT_WORK
            else FactorKind.LIFECYCLE_FACTOR
        ),
    )
    candidate, error = _candidate(activity, source, CandidateOrigin.LOCAL)

    assert error is None
    assert candidate is not None
    assert candidate.resolved_activity_value == pytest.approx(10)
    assert candidate.resolved_activity_unit == quantity_unit
    assert candidate.resolved_quantity_kg is None
    assert candidate.total_emissions_kgco2e == pytest.approx(10 * factor_value)


@pytest.mark.parametrize(
    (
        "quantity",
        "quantity_unit",
        "factor_unit",
        "factor_value",
        "dimension",
        "expected_activity",
        "expected_total",
    ),
    (
        (2, "MWh", "kgCO2e/kWh", 0.5, ActivityDimension.ENERGY, 2_000, 1_000),
        (2_000, "kWh", "kgCO2e/MWh", 500, ActivityDimension.ENERGY, 2, 1_000),
        (
            15_000,
            "kgkm",
            "kgCO2e/tkm",
            0.066,
            ActivityDimension.TRANSPORT_WORK,
            15,
            0.99,
        ),
        (
            15,
            "tkm",
            "kgCO2e/kgkm",
            0.000066,
            ActivityDimension.TRANSPORT_WORK,
            15_000,
            0.99,
        ),
        (4_000, "L", "kgCO2e/m3", 2, ActivityDimension.VOLUME, 4, 8),
        (4, "m3", "kgCO2e/L", 0.002, ActivityDimension.VOLUME, 4_000, 8),
    ),
)
def test_non_mass_scale_directions_use_aligned_activity_without_fake_kg(
    quantity: float,
    quantity_unit: str,
    factor_unit: str,
    factor_value: float,
    dimension: ActivityDimension,
    expected_activity: float,
    expected_total: float,
) -> None:
    activity = _activity(quantity, quantity_unit, factor_unit, dimension=dimension)
    candidate, error = _candidate(
        activity,
        _source(
            factor_unit,
            factor_value,
            subject_type=(
                FactorSubjectType.ENERGY
                if dimension == ActivityDimension.ENERGY
                else FactorSubjectType.TRANSPORT
                if dimension == ActivityDimension.TRANSPORT_WORK
                else FactorSubjectType.PROCESS
            ),
        ),
        CandidateOrigin.LOCAL,
    )

    assert error is None
    assert candidate is not None
    assert candidate.resolved_activity_value == pytest.approx(expected_activity)
    assert candidate.resolved_quantity_kg is None
    assert candidate.total_emissions_kgco2e == pytest.approx(expected_total)


def test_derived_factor_uses_denominator_aligned_activity_not_kg_compatibility() -> None:
    base, error = _candidate(
        _activity(1, "t", "kgCO2e/t"),
        _source("kgCO2e/t", 2_000),
        CandidateOrigin.LOCAL,
    )
    assert error is None
    assert base is not None

    derived = derive_candidate(
        base,
        candidate_id="derived-per-tonne",
        resolution_type=ResolutionType.PROCESS_ADJUSTED,
        factor_value=2_500,
    )

    assert derived.resolved_activity_value == pytest.approx(1)
    assert derived.resolved_activity_unit == "t"
    assert derived.resolved_quantity_kg == pytest.approx(1_000)
    assert derived.total_emissions_kgco2e == pytest.approx(2_500)


@pytest.mark.parametrize(
    ("factor_value", "factor_unit", "expected_total"),
    (
        (1.0, "gCO2e/kg", 0.001),
        (1.0, "kgCO2e/kg", 1.0),
        (1.0, "tCO2e/t", 1_000.0),
    ),
)
def test_total_preview_normalizes_impact_numerator_to_kgco2e(
    factor_value: float,
    factor_unit: str,
    expected_total: float,
) -> None:
    quantity = 1 if factor_unit.endswith("/kg") else 1
    quantity_unit = factor_unit.rsplit("/", 1)[1]
    candidate, error = _candidate(
        _activity(quantity, quantity_unit, factor_unit),
        _source(factor_unit, factor_value),
        CandidateOrigin.LOCAL,
    )

    assert error is None
    assert candidate is not None
    assert candidate.total_emissions_kgco2e == pytest.approx(expected_total)
    assert expected_total_emissions(candidate) == pytest.approx(expected_total)


def test_candidate_rejects_kg_compatibility_field_for_non_mass_activity() -> None:
    candidate, error = _candidate(
        _activity(1, "kg", "kgCO2e/kg"),
        _source("kgCO2e/kg", 1),
        CandidateOrigin.LOCAL,
    )
    assert error is None
    assert candidate is not None

    with pytest.raises(ValueError, match="only for mass"):
        replace(candidate, activity_dimension="ENERGY")


def test_legacy_kg_fallback_rejects_non_mass_factor() -> None:
    candidate, error = _candidate(
        _activity(1, "kg", "kgCO2e/kg"),
        _source("kgCO2e/kg", 1),
        CandidateOrigin.LOCAL,
    )
    assert error is None
    assert candidate is not None
    legacy_shape: Candidate = replace(
        candidate,
        factor_unit="kgCO2e/kWh",
        resolved_activity_value=None,
        resolved_activity_unit=None,
        activity_dimension=None,
        resolved_quantity_kg=1,
        total_emissions_kgco2e=None,
    )

    with pytest.raises(ValueError, match="requires a mass factor"):
        expected_total_emissions(legacy_shape)


@pytest.mark.asyncio
async def test_lock_rejects_misaligned_application_unit_even_when_hashes_match() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/t", 2_000),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="misaligned-lock",
        material_name="unit field material",
        quantity=1,
        quantity_unit="t",
        target_factor_unit="kgCO2e/t",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = result.candidates[0]
    tampered = replace(
        candidate,
        resolved_activity_value=1,
        resolved_activity_unit="kg",
        resolved_quantity_kg=1_000,
        total_emissions_kgco2e=2_000,
    )
    tampered_result = replace(result, candidates=(tampered,))
    engine.store.recommendations[result.request_id] = tampered_result
    await engine.approve(result.request_id, tampered.candidate_id, "reviewer")

    with pytest.raises(ValueError, match="denominator-aligned"):
        await engine.lock(result.request_id, tampered.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_lock_rejects_kg_field_inconsistent_with_mass_activity() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/t", 2_000),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="wrong-kg-lock",
        material_name="unit field material",
        quantity=1,
        quantity_unit="t",
        target_factor_unit="kgCO2e/t",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = replace(result.candidates[0], resolved_quantity_kg=1)
    engine.store.recommendations[result.request_id] = replace(
        result,
        candidates=(candidate,),
    )
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")

    with pytest.raises(ValueError, match="inconsistent"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quantity", "quantity_unit", "wrong_kg", "dimension"),
    (
        (1e-9, "g", 1e-9, "MASS"),
        (1, "t", 1, None),
    ),
)
async def test_lock_rejects_relative_kg_errors_and_missing_dimension_bypass(
    quantity: float,
    quantity_unit: str,
    wrong_kg: float,
    dimension: str | None,
) -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/kg", 2),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id=f"kg-bypass-{quantity_unit}",
        material_name="unit field material",
        quantity=quantity,
        quantity_unit=quantity_unit,
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = replace(
        result.candidates[0],
        activity_dimension=dimension,
        resolved_quantity_kg=wrong_kg,
    )
    engine.store.recommendations[result.request_id] = replace(
        result,
        candidates=(candidate,),
    )
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")

    with pytest.raises(ValueError, match="inconsistent"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_lock_rejects_non_finite_recomputed_total_after_float_overflow() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/kg", 2),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="overflow-lock",
        material_name="unit field material",
        quantity=1,
        quantity_unit="kg",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = replace(
        result.candidates[0],
        resolved_activity_value=1e308,
        resolved_quantity_kg=1e308,
        total_emissions_kgco2e=0,
    )
    engine.store.recommendations[result.request_id] = replace(
        result,
        candidates=(candidate,),
    )
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")

    with pytest.raises(ValueError, match="must be finite"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_lock_rejects_non_finite_legacy_kg_fallback_total() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/kg", 2),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="legacy-overflow-lock",
        material_name="unit field material",
        quantity=1,
        quantity_unit="kg",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = replace(
        result.candidates[0],
        resolved_activity_value=None,
        resolved_activity_unit=None,
        activity_dimension=None,
        resolved_quantity_kg=1e308,
        total_emissions_kgco2e=0,
    )
    engine.store.recommendations[result.request_id] = replace(
        result,
        candidates=(candidate,),
    )
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")

    with pytest.raises(ValueError, match="must be finite"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")


@pytest.mark.asyncio
async def test_new_lock_preserves_both_application_fields_and_frozen_snapshot() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/t", 2_000),))
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="unit-field-lock",
        material_name="unit field material",
        quantity=1_000_000,
        quantity_unit="g",
        target_factor_unit="kgCO2e/t",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    before = (
        locked.content_sha256,
        locked.evidence_snapshot.snapshot_sha256 if locked.evidence_snapshot else None,
        locked.evidence_snapshot.canonical_bytes if locked.evidence_snapshot else None,
    )

    await engine._append_trace(
        result.request_id,
        "post_lock_note",
        "later annotation",
        {},
    )
    stored = await engine.locked(result.request_id)

    assert locked.candidate.resolved_activity_value == pytest.approx(1)
    assert locked.candidate.resolved_activity_unit == "t"
    assert locked.candidate.resolved_quantity_kg == pytest.approx(1_000)
    assert locked.candidate.total_emissions_kgco2e == pytest.approx(2_000)
    assert stored is not None
    assert (
        stored.content_sha256,
        stored.evidence_snapshot.snapshot_sha256 if stored.evidence_snapshot else None,
        stored.evidence_snapshot.canonical_bytes if stored.evidence_snapshot else None,
    ) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("factor_unit", "factor_value", "expected_activity"),
    (("kgCO2e/g", 0.002, 1_000), ("kgCO2e/t", 2_000, 0.001)),
)
async def test_reference_flow_aligns_mass_to_factor_denominator_before_lock(
    factor_unit: str,
    factor_value: float,
    expected_activity: float,
) -> None:
    source = replace(_source(factor_unit, factor_value), product_form="piece")
    flow = ReferenceFlowRecord(
        "unit-field-flow",
        "unit field material",
        "piece",
        1,
        ParameterEvidence(
            "unit-field-mass",
            "mass_per_piece",
            1,
            "kg/piece",
            ParameterSourceType.FORMAL_STANDARD,
            "PUBLIC_SYNTHETIC",
            "evidence://unit-field-mass",
        ),
        product_form="piece",
    )
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((source,)),
        reference_flows=InMemoryReferenceFlowRepository((flow,)),
    )
    result = await engine.resolve(ResolutionRequest(
        request_id=f"reference-flow-{factor_unit}",
        material_name="unit field material",
        quantity=1,
        quantity_unit="piece",
        product_form="piece",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    candidate = result.candidates[0]

    assert candidate.resolved_activity_value == pytest.approx(expected_activity)
    assert candidate.resolved_activity_unit == factor_unit.rsplit("/", 1)[1]
    assert candidate.resolved_quantity_kg == pytest.approx(1)
    assert candidate.total_emissions_kgco2e == pytest.approx(2)
    await engine.approve(
        result.request_id,
        candidate.candidate_id,
        "reviewer",
        mode=ApprovalMode.ASSUMPTION_ACCEPTANCE,
    )
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    assert locked.candidate.content_sha256 == candidate.content_sha256


def test_public_api_omits_unit_application_internals_while_admin_debug_retains_them() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "reviewer",
            "tenant",
            "project",
            ("resolve:execute", "resolve:debug"),
        )

    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("kgCO2e/t", 2_000),))
    )
    payload = {
        "request_id": "unit-field-public",
        "material_name": "unit field material",
        "quantity": 1,
        "quantity_unit": "t",
        "target_factor_unit": "kgCO2e/t",
        "geography": "CN",
        "year": 2025,
        "subject_type": "raw_material",
    }
    with TestClient(create_admin_app(engine=engine, authorizer=allow)) as client:
        public = client.post("/api/v1/resolve", json=payload)
        debug = client.post("/api/v1/debug/resolve", json={**payload, "request_id": "unit-field-debug"})

    assert public.status_code == debug.status_code == 200
    for field in (
        "resolved_activity_value",
        "resolved_activity_unit",
        "activity_dimension",
        "resolved_quantity_kg",
        "total_emissions_kgco2e",
    ):
        assert field not in public.text
        assert field in debug.json()["candidates"][0]
