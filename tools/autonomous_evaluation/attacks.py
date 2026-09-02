"""Generated state-machine and API attacks for the offline autonomous evaluator."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any, Awaitable, Callable

from a1_factor_engine.adapters import (
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
    InMemoryResolutionStore,
)
from a1_factor_engine.engine import A1FactorResolutionEngine
from a1_factor_engine.models import (
    Candidate,
    CandidateOrigin,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    Recommendation,
    ResolutionRequest,
    ResolutionStatus,
    ResolutionTrace,
    ResolutionType,
    ResultTier,
    SourceRecord,
)


def _source(
    source_id: str = "autoeval:workflow:steel",
    *,
    value: float = 1.0,
    metadata: dict[str, str] | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="CFR public-synthetic autonomous evaluation",
        locator=f"synthetic://autoeval/workflow/{source_id}",
        material_name="autoeval workflow steel",
        factor_value=value,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2025,
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        indicator="GWP-total",
        declared_product="autoeval workflow steel",
        boundary_modules=("A1", "A2", "A3"),
        source_document_sha256="a" * 64,
        metadata=metadata or {},
    )


def _request(request_id: str) -> ResolutionRequest:
    return ResolutionRequest(
        request_id=request_id,
        material_name="autoeval workflow steel",
        quantity=1,
        subject_type=FactorSubjectType.RAW_MATERIAL,
    )


async def _resolved_engine(
    request_id: str,
    source: SourceRecord | None = None,
) -> tuple[A1FactorResolutionEngine, Recommendation]:
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([source or _source()])
    )
    return engine, await engine.resolve(_request(request_id))


async def _expect_failure(
    name: str,
    operation: Callable[[], Awaitable[Any]],
    expected_types: tuple[type[BaseException], ...] = (ValueError, KeyError),
) -> dict[str, Any]:
    try:
        await operation()
    except expected_types as exc:
        return {
            "attack_id": name,
            "passed": True,
            "expected": "fail_closed",
            "observed": "rejected",
            "exception_type": type(exc).__name__,
            "sanitized_message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - unexpected exception is benchmark evidence
        return {
            "attack_id": name,
            "passed": False,
            "expected": "fail_closed",
            "observed": "unexpected_exception",
            "exception_type": type(exc).__name__,
            "sanitized_message": str(exc),
        }
    return {
        "attack_id": name,
        "passed": False,
        "expected": "fail_closed",
        "observed": "operation_succeeded",
        "exception_type": None,
        "sanitized_message": "",
    }


async def _approve_unreturned() -> dict[str, Any]:
    engine, result = await _resolved_engine("autoeval-attack-unreturned")
    return await _expect_failure(
        "APPROVE_UNRETURNED_CANDIDATE",
        lambda: engine.approve(result.request_id, "local:not-returned", "reviewer"),
    )


async def _standard_reference_only() -> dict[str, Any]:
    capped = _source(metadata={"result_tier_cap": ResultTier.REFERENCE_ONLY.value})
    engine, result = await _resolved_engine("autoeval-attack-reference", capped)
    if not result.reviewable_candidates:
        return {
            "attack_id": "STANDARD_APPROVE_REFERENCE_ONLY",
            "passed": False,
            "expected": "fail_closed",
            "observed": "reference_candidate_missing",
            "exception_type": None,
            "sanitized_message": "",
        }
    candidate_id = result.reviewable_candidates[0].candidate_id
    return await _expect_failure(
        "STANDARD_APPROVE_REFERENCE_ONLY",
        lambda: engine.approve(result.request_id, candidate_id, "reviewer"),
    )


async def _approve_hard_blocked() -> dict[str, Any]:
    source = _source("autoeval:workflow:hard-blocked")
    candidate = Candidate(
        candidate_id="proxy:autoeval-hard-blocked",
        origin=CandidateOrigin.PROXY,
        source=source,
        provenance=source.provenance,
        factor_value=source.factor_value,
        factor_unit=source.factor_unit,
        score=0.9,
        reasons=("synthetic hard-process attack",),
        limitations=("unadjusted process proxy",),
        dimensions={},
        resolution_type=ResolutionType.UNADJUSTED_PROCESS_PROXY,
        result_tier=ResultTier.PRIMARY_RECOMMENDATION,
    )
    request_id = "autoeval-attack-hard-blocked"
    trace = ResolutionTrace("autoeval-trace-hard", request_id, "a" * 64)
    recommendation = Recommendation(
        request_id=request_id,
        status=ResolutionStatus.RECOMMENDATION_READY,
        candidates=(candidate,),
        trace=trace,
    )
    store = InMemoryResolutionStore()
    await store.save_resolution_run(recommendation, trace)
    engine = A1FactorResolutionEngine(store=store)
    return await _expect_failure(
        "APPROVE_HARD_BLOCKED_CANDIDATE",
        lambda: engine.approve(request_id, candidate.candidate_id, "reviewer"),
    )


async def _locked_result_immutable() -> dict[str, Any]:
    engine, result = await _resolved_engine("autoeval-attack-lock")
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    mutation_rejected = False
    try:
        locked.reviewer = "attacker"  # type: ignore[misc]
    except FrozenInstanceError:
        mutation_rejected = True
    different = await _expect_failure(
        "LOCKED_RESULT_DIFFERENT_CANDIDATE",
        lambda: engine.lock(result.request_id, "local:different", "attacker"),
    )
    return {
        "attack_id": "MODIFY_LOCKED_RESULT",
        "passed": mutation_rejected and different["passed"],
        "expected": "immutable",
        "observed": "immutable" if mutation_rejected else "mutable",
        "exception_type": different["exception_type"],
        "sanitized_message": different["sanitized_message"],
    }


async def _old_catalog_replay() -> dict[str, Any]:
    first = _source("autoeval:workflow:catalog-v1", value=1.0)
    engine, result = await _resolved_engine("autoeval-attack-old-catalog", first)
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer")
    locked = await engine.lock(result.request_id, candidate.candidate_id, "reviewer")
    preserved = await engine.locked(result.request_id)
    passed = bool(
        preserved is locked
        and preserved.candidate.factor_value == 1.0
        and preserved.candidate.source.source_id == first.source_id
    )
    return {
        "attack_id": "OLD_CATALOG_REPLAY",
        "passed": passed,
        "expected": "locked_snapshot_preserved",
        "observed": "preserved" if passed else "changed",
        "exception_type": None,
        "sanitized_message": "",
    }


async def _catalog_hash_tamper() -> dict[str, Any]:
    payload = {
        "catalog_version": "autoeval-tamper/v1",
        "database": {"name": "autoeval-tamper", "sha256": "2" * 64},
        "records": [],
    }
    repository = HttpCatalogFactorRepository(
        endpoint="synthetic://autoeval/tamper",
        expected_sha256="1" * 64,
        fetch_json=lambda _endpoint: payload,
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    return await _expect_failure(
        "CATALOG_HASH_TAMPER",
        lambda: engine.resolve(_request("autoeval-attack-hash-tamper")),
    )


async def _rejected_reapproval() -> dict[str, Any]:
    engine, result = await _resolved_engine("autoeval-attack-reject")
    candidate = result.candidates[0]
    await engine.reject(result.request_id, candidate.candidate_id, "reviewer")
    return await _expect_failure(
        "REJECTED_CANDIDATE_REAPPROVAL",
        lambda: engine.approve(result.request_id, candidate.candidate_id, "attacker"),
    )


async def _concurrent_duplicate_approval_lock() -> dict[str, Any]:
    engine, result = await _resolved_engine("autoeval-attack-concurrent")
    candidate = result.candidates[0]
    approvals = await asyncio.gather(
        engine.approve(result.request_id, candidate.candidate_id, "reviewer-a"),
        engine.approve(result.request_id, candidate.candidate_id, "reviewer-b"),
        return_exceptions=True,
    )
    approval_successes = sum(not isinstance(value, BaseException) for value in approvals)
    stored = await engine.store.get_approval(result.request_id, candidate.candidate_id)
    locks = await asyncio.gather(
        engine.lock(result.request_id, candidate.candidate_id, "reviewer-a"),
        engine.lock(result.request_id, candidate.candidate_id, "reviewer-b"),
        return_exceptions=True,
    )
    lock_values = [value for value in locks if not isinstance(value, BaseException)]
    # Duplicate approval must have one atomic winner; duplicate lock may idempotently
    # return that one immutable snapshot.
    passed = bool(
        approval_successes == 1
        and stored is not None
        and lock_values
        and all(value is lock_values[0] for value in lock_values)
    )
    return {
        "attack_id": "CONCURRENT_DUPLICATE_APPROVAL_LOCK",
        "passed": passed,
        "expected": "one_atomic_approval_and_one_immutable_lock",
        "observed": {
            "approval_successes": approval_successes,
            "approval_failures": len(approvals) - approval_successes,
            "lock_successes": len(lock_values),
            "lock_failures": len(locks) - len(lock_values),
            "stored_reviewer": stored.reviewer if stored else None,
        },
        "exception_type": None,
        "sanitized_message": "",
    }


async def run_state_machine_attacks() -> list[dict[str, Any]]:
    """Run all autonomous workflow attacks in a fixed order."""

    operations = (
        _approve_unreturned,
        _standard_reference_only,
        _approve_hard_blocked,
        _locked_result_immutable,
        _old_catalog_replay,
        _catalog_hash_tamper,
        _rejected_reapproval,
        _concurrent_duplicate_approval_lock,
    )
    return [await operation() for operation in operations]
