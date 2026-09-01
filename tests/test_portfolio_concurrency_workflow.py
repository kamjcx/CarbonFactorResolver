from __future__ import annotations

import asyncio
from math import isfinite
from time import perf_counter
from typing import Any

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    ApprovalStatus,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    ResolutionRequest,
    ResolutionStatus,
    ResultTier,
    SourceQualityStatus,
    SourceRecord,
)
from a1_factor_engine.adapters import HttpCatalogFactorRepository, InMemoryFactorRepository
from a1_factor_engine.models import resolution_request_fingerprint
from tools.portfolio_validation import aggregate


def steel_source(source_id: str = "workflow-steel", factor_value: float = 1.0) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="workflow fixture",
        locator=f"fixture://portfolio-workflow/{source_id}",
        material_name="steel coil",
        factor_value=factor_value,
        factor_unit="kgCO2e/kg",
        product_form="coil",
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        source_quality_status=SourceQualityStatus.VERIFIED,
        admission_eligible=True,
        indicator="GWP-total",
        declared_product="steel coil",
        boundary_modules=("A1", "A2", "A3"),
    )


def steel_request(request_id: str, *, quantity: float = 1.0) -> ResolutionRequest:
    return ResolutionRequest(
        request_id=request_id,
        material_name="steel coil",
        quantity=quantity,
        quantity_unit="kg",
        product_form="coil",
        subject_type=FactorSubjectType.RAW_MATERIAL,
    )


def resolution_signature(result: Any) -> tuple[Any, ...]:
    """Compare deterministic business output, excluding run IDs, timestamps and latency."""

    trace = result.trace
    assert trace is not None and trace.database_anchor is not None
    return (
        result.status,
        result.follow_up,
        result.candidates,
        result.reviewable_candidates,
        result.reviewable_candidate_reasons,
        result.diagnostic_candidates,
        result.accounting_assignments,
        tuple(entry.stage for entry in trace.entries),
        trace.database_anchor.identity,
    )


async def timed_resolve(
    engine: A1FactorResolutionEngine, request: ResolutionRequest
) -> tuple[Any, float]:
    started = perf_counter()
    result = await engine.resolve(request)
    return result, (perf_counter() - started) * 1000


@pytest.mark.asyncio
async def test_fifty_concurrent_resolutions_are_trace_isolated_and_serially_equivalent() -> None:
    source = steel_source()
    concurrent_engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    )
    concurrent_pairs = await asyncio.gather(*(
        timed_resolve(concurrent_engine, steel_request(f"concurrent-{index:02d}"))
        for index in range(50)
    ))
    concurrent_results = tuple(pair[0] for pair in concurrent_pairs)
    latencies = tuple(pair[1] for pair in concurrent_pairs)

    serial_engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source])
    )
    serial_results = tuple([
        await serial_engine.resolve(steel_request(f"serial-{index:02d}"))
        for index in range(50)
    ])

    traces = tuple([
        await concurrent_engine.trace(result.request_id)
        for result in concurrent_results
    ])
    assert len(concurrent_results) == 50
    assert len({id(trace) for trace in traces}) == 50
    assert len({trace.trace_id for trace in traces if trace is not None}) == 50
    for result, trace in zip(concurrent_results, traces, strict=True):
        assert trace is not None
        assert result.trace is trace
        assert result.request_id == trace.request_id
        assert [entry.revision for entry in trace.entries] == list(
            range(1, trace.revision + 1)
        )

    assert [resolution_signature(result) for result in concurrent_results] == [
        resolution_signature(result) for result in serial_results
    ]

    metric_rows = tuple({
        "expected_decision": "retrieve",
        "observed_ids": [source.source_id],
        "acceptable_ids": [source.source_id],
        "forbidden_ids": [],
        "observed_decision": "retrieve",
        "request": {
            "subject_type": FactorSubjectType.RAW_MATERIAL.value,
            "boundary": "cradle-to-gate",
        },
        "latency_ms": latency,
    } for latency in latencies)
    metrics = aggregate(metric_rows, {
        source.source_id: {
            "subject_type": FactorSubjectType.RAW_MATERIAL.value,
            "boundary": "cradle-to-gate",
        }
    })
    percentiles = tuple(
        float(metrics[key])
        for key in ("p50_latency_ms", "p95_latency_ms", "p99_latency_ms")
    )
    assert all(isfinite(value) and value >= 0 for value in percentiles)
    assert percentiles == tuple(sorted(percentiles))


class BarrierFactorRepository:
    """Force two resolution graphs past the duplicate-ID precheck before commit."""

    def __init__(self, source: SourceRecord) -> None:
        self.delegate = InMemoryFactorRepository([source])
        self.arrivals = 0
        self.ready = asyncio.Event()

    async def search(self, intent):
        self.arrivals += 1
        if self.arrivals == 2:
            self.ready.set()
        await self.ready.wait()
        return await self.delegate.search(intent)


@pytest.mark.asyncio
async def test_concurrent_duplicate_request_id_has_one_atomic_winner() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=BarrierFactorRepository(steel_source("duplicate-steel"))
    )
    requests = (
        steel_request("concurrent-duplicate", quantity=1),
        steel_request("concurrent-duplicate", quantity=2),
    )
    outcomes = await asyncio.gather(
        *(engine.resolve(item) for item in requests),
        return_exceptions=True,
    )

    winners = [item for item in outcomes if not isinstance(item, BaseException)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(winners) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValueError)
    assert "duplicate request_id" in str(failures[0])

    winner_index = outcomes.index(winners[0])
    stored = await engine.state("concurrent-duplicate")
    trace = await engine.trace("concurrent-duplicate")
    assert stored is winners[0]
    assert trace is not None and stored.trace is trace
    assert trace.request_fingerprint == resolution_request_fingerprint(
        requests[winner_index]
    )


def catalog_payload(version: str, digest: str, factor_value: float) -> dict[str, Any]:
    return {
        "catalog_version": version,
        "database": {"name": "workflow-catalog", "sha256": digest},
        "records": [{
            "record_id": "catalog-steel",
            "source_quality_status": "VERIFIED",
            "admission_eligible": True,
            "subject_type": "raw_material",
            "source": "workflow catalog fixture",
            "source_type": "external_database",
            "name": "steel coil",
            "primary_value": factor_value,
            "primary_unit": "kgCO2e/kg",
            "factor_kind": "lifecycle_factor",
            "indicator": "GWP-total",
            "declared_product": "steel coil",
            "product_form": "coil",
            "boundary": "cradle-to-gate",
            "boundary_modules": ["A1", "A2", "A3"],
            "source_document_locator": f"fixture://workflow-catalog/{version}",
            "source_document_sha256": digest,
        }],
    }


@pytest.mark.asyncio
async def test_approval_lock_and_catalog_refresh_preserve_locked_snapshot() -> None:
    first_digest = "1" * 64
    second_digest = "2" * 64
    current = {"payload": catalog_payload("workflow-v1", first_digest, 1.0)}
    repository = HttpCatalogFactorRepository(
        endpoint="fixture://workflow-catalog",
        fetch_json=lambda _endpoint: current["payload"],
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)

    first = await engine.resolve(steel_request("catalog-before"))
    assert first.status == ResolutionStatus.RECOMMENDATION_READY
    candidate = first.candidates[0]
    with pytest.raises(ValueError, match="approved before locking"):
        await engine.lock(first.request_id, candidate.candidate_id, "reviewer")

    approval = await engine.approve(
        first.request_id, candidate.candidate_id, "reviewer"
    )
    locked = await engine.lock(first.request_id, candidate.candidate_id, "reviewer")
    assert approval.status == ApprovalStatus.APPROVED
    assert locked.approval.status == ApprovalStatus.LOCKED
    locked_snapshot = (
        locked.candidate.factor_value,
        locked.candidate.total_emissions_kgco2e,
        dict(locked.candidate.source.metadata),
        locked.candidate.provenance,
        locked.locked_at,
    )

    current["payload"] = catalog_payload("workflow-v2", second_digest, 2.0)
    second = await engine.resolve(steel_request("catalog-after"))
    assert second.candidates[0].factor_value == pytest.approx(2.0)
    assert second.trace is not None and second.trace.database_anchor is not None
    assert second.trace.database_anchor.database_sha256 == second_digest

    stored_lock = await engine.locked(first.request_id)
    assert stored_lock is locked
    assert (
        stored_lock.candidate.factor_value,
        stored_lock.candidate.total_emissions_kgco2e,
        dict(stored_lock.candidate.source.metadata),
        stored_lock.candidate.provenance,
        stored_lock.locked_at,
    ) == locked_snapshot
    assert stored_lock.candidate.source.metadata["catalog_version"] == "workflow-v1"
    assert stored_lock.candidate.source.metadata["database_sha256"] == first_digest
    assert first.trace is not None and first.trace.database_anchor is not None
    assert first.trace.database_anchor.database_sha256 == first_digest
    assert await engine.lock(
        first.request_id, candidate.candidate_id, "another reviewer"
    ) == locked


@pytest.mark.asyncio
async def test_reference_override_requires_reason_and_records_it_on_lock() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([steel_source("reference-steel")])
    )
    result = await engine.resolve(ResolutionRequest(
        request_id="reference-override",
        material_name="premium steel coil",
        quantity=1,
        product_form="coil",
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))
    assert result.status == ResolutionStatus.REFERENCE_REVIEW_REQUIRED
    candidate = result.reviewable_candidates[0]
    assert candidate.result_tier == ResultTier.REFERENCE_ONLY

    with pytest.raises(ValueError, match="reference_override"):
        await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    with pytest.raises(ValueError, match="non-empty reason"):
        await engine.approve(
            result.request_id,
            candidate.candidate_id,
            "reviewer",
            note="   ",
            mode=ApprovalMode.REFERENCE_OVERRIDE,
        )

    reason = "accepted as a documented family reference for screening"
    approval = await engine.approve(
        result.request_id,
        candidate.candidate_id,
        "reviewer",
        note=reason,
        mode=ApprovalMode.REFERENCE_OVERRIDE,
    )
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    assert approval.mode == ApprovalMode.REFERENCE_OVERRIDE
    assert approval.note == reason
    assert locked.approval.mode == ApprovalMode.REFERENCE_OVERRIDE
    assert locked.approval.note == reason
    trace = await engine.trace(result.request_id)
    assert trace is not None
    assert trace.latest("lock").details["override_reason"] == reason


@pytest.mark.asyncio
async def test_human_rejection_prevents_locking_and_remains_traceable() -> None:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([steel_source("rejected-steel")])
    )
    result = await engine.resolve(steel_request("human-rejection"))
    candidate = result.candidates[0]
    rejection = await engine.reject(
        result.request_id, candidate.candidate_id, "reviewer", "evidence not accepted"
    )
    assert rejection.status == ApprovalStatus.REJECTED

    with pytest.raises(ValueError, match="approved before locking"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    trace = await engine.trace(result.request_id)
    assert trace is not None
    event = trace.latest("human_approval")
    assert event is not None
    assert event.message == "candidate rejected"
    assert event.details["note"] == "evidence not accepted"

    with pytest.raises(ValueError, match="rejected candidate cannot be approved"):
        await engine.approve(result.request_id, candidate.candidate_id, "second-reviewer")

    preserved = await engine.store.get_approval(result.request_id, candidate.candidate_id)
    assert preserved == rejection
