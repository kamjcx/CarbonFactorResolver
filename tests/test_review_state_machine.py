from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    ApprovalRecord,
    ApprovalStatus,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    ResolutionRequest,
    ReviewStateConflictError,
    SourceRecord,
    StaleReviewRevisionError,
)
from a1_factor_engine.adapters import InMemoryFactorRepository, InMemoryResolutionStore
from a1_factor_engine.integrity import PersistenceIntegrityError
from a1_factor_engine.models import TraceEntry


def _source(source_id: str, factor_value: float) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="PUBLIC_SYNTHETIC",
        locator=f"evidence://{source_id}",
        material_name="review material",
        factor_value=factor_value,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2025,
        boundary="cradle-to-gate",
        boundary_modules=("A1", "A2", "A3"),
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        indicator="GWP-total",
        declared_product="review material",
        source_document_sha256=("ab" if source_id.endswith("a") else "cd") * 32,
    )


def _engine() -> A1FactorResolutionEngine:
    return A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((
            _source("review-a", 1),
            _source("review-b", 2),
        ))
    )


async def _recommend(engine: A1FactorResolutionEngine, request_id: str):
    result = await engine.resolve(ResolutionRequest(
        request_id=request_id,
        material_name="review material",
        quantity=1,
        quantity_unit="kg",
        geography="CN",
        year=2025,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        top_k=2,
    ))
    assert len(result.candidates) == 2
    return result, result.candidates[0], result.candidates[1]


@pytest.mark.asyncio
async def test_approve_a_then_reject_b_then_lock_a_is_composable() -> None:
    engine = _engine()
    result, candidate_a, candidate_b = await _recommend(engine, "review-order-red")

    await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer-a")
    await engine.reject(
        result.request_id,
        candidate_b.candidate_id,
        "reviewer-b",
        "not selected",
    )
    locked = await engine.lock(result.request_id, candidate_a.candidate_id, "reviewer-a")

    assert locked.candidate.candidate_id == candidate_a.candidate_id


@pytest.mark.asyncio
async def test_reject_b_then_approve_a_then_lock_a_is_composable() -> None:
    engine = _engine()
    result, candidate_a, candidate_b = await _recommend(engine, "review-reverse")

    await engine.reject(result.request_id, candidate_b.candidate_id, "reviewer-b", "not selected")
    await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer-a")
    locked = await engine.lock(result.request_id, candidate_a.candidate_id, "reviewer-a")

    assert locked.candidate.candidate_id == candidate_a.candidate_id


@pytest.mark.asyncio
async def test_exact_decision_and_lock_replays_are_idempotent() -> None:
    engine = _engine()
    result, candidate_a, _ = await _recommend(engine, "review-replay")

    before = (await engine.trace(result.request_id)).revision
    first = await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer", "selected")
    after_first = (await engine.trace(result.request_id)).revision
    replay = await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer", "selected")
    assert replay is first
    assert after_first == before + 1
    assert (await engine.trace(result.request_id)).revision == after_first

    locked = await engine.lock(result.request_id, candidate_a.candidate_id, "locker")
    after_lock = (await engine.trace(result.request_id)).revision
    retry = await engine.lock(result.request_id, candidate_a.candidate_id, "different-retry-actor")
    assert retry is locked
    assert retry.reviewer == "locker"
    assert (await engine.trace(result.request_id)).revision == after_lock


@pytest.mark.asyncio
async def test_same_candidate_conflicts_fail_closed() -> None:
    engine = _engine()
    result, candidate_a, _ = await _recommend(engine, "review-conflict")
    await engine.reject(result.request_id, candidate_a.candidate_id, "reviewer", "bad evidence")

    with pytest.raises(ReviewStateConflictError, match="rejected candidate"):
        await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer")
    with pytest.raises(ReviewStateConflictError, match="different terminal"):
        await engine.reject(result.request_id, candidate_a.candidate_id, "other", "bad evidence")


@pytest.mark.asyncio
async def test_explicit_stale_revision_fails_without_trace_mutation() -> None:
    engine = _engine()
    result, candidate_a, _ = await _recommend(engine, "review-stale")
    trace = await engine.trace(result.request_id)
    assert trace is not None
    stale = trace.revision
    await engine.approve(
        result.request_id,
        candidate_a.candidate_id,
        "reviewer",
        expected_trace_revision=stale,
    )
    committed = (await engine.trace(result.request_id)).revision

    with pytest.raises(StaleReviewRevisionError):
        await engine.lock(
            result.request_id,
            candidate_a.candidate_id,
            "reviewer",
            expected_trace_revision=stale,
        )
    assert (await engine.trace(result.request_id)).revision == committed


@pytest.mark.asyncio
async def test_engine_reconstruction_over_same_store_recovers_review_state() -> None:
    store = InMemoryResolutionStore()
    first = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((_source("review-a", 1), _source("review-b", 2))),
        store=store,
    )
    result, candidate_a, candidate_b = await _recommend(first, "review-recovery")
    await first.approve(result.request_id, candidate_a.candidate_id, "reviewer-a")

    restarted = A1FactorResolutionEngine(store=store)
    await restarted.reject(result.request_id, candidate_b.candidate_id, "reviewer-b")
    locked = await restarted.lock(result.request_id, candidate_a.candidate_id, "reviewer-a")
    assert locked.candidate.candidate_id == candidate_a.candidate_id


@pytest.mark.asyncio
async def test_concurrent_legal_decisions_compose_and_competing_approvals_do_not() -> None:
    engine = _engine()
    result, candidate_a, candidate_b = await _recommend(engine, "review-concurrent-compose")
    composed = await asyncio.gather(
        engine.approve(result.request_id, candidate_a.candidate_id, "reviewer-a"),
        engine.reject(result.request_id, candidate_b.candidate_id, "reviewer-b"),
    )
    assert {item.status for item in composed} == {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}
    assert (await engine.lock(result.request_id, candidate_a.candidate_id, "reviewer-a")).candidate == candidate_a

    competing = _engine()
    result, candidate_a, candidate_b = await _recommend(competing, "review-concurrent-conflict")
    outcomes = await asyncio.gather(
        competing.approve(result.request_id, candidate_a.candidate_id, "reviewer-a"),
        competing.approve(result.request_id, candidate_b.candidate_id, "reviewer-b"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ApprovalRecord) for item in outcomes) == 1
    assert sum(isinstance(item, ReviewStateConflictError) for item in outcomes) == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_decisions_and_locks_commit_one_event() -> None:
    engine = _engine()
    result, candidate_a, _ = await _recommend(engine, "review-concurrent-idempotent")
    before = (await engine.trace(result.request_id)).revision
    decisions = await asyncio.gather(*(
        engine.approve(result.request_id, candidate_a.candidate_id, "reviewer", "selected")
        for _ in range(8)
    ))
    assert len({item.content_sha256 for item in decisions}) == 1
    assert (await engine.trace(result.request_id)).revision == before + 1

    locks = await asyncio.gather(*(
        engine.lock(result.request_id, candidate_a.candidate_id, "locker")
        for _ in range(8)
    ))
    assert len({item.content_sha256 for item in locks}) == 1
    assert (await engine.trace(result.request_id)).revision == before + 2


@pytest.mark.asyncio
async def test_mutated_approval_trace_prefix_fails_integrity_check() -> None:
    engine = _engine()
    result, candidate_a, candidate_b = await _recommend(engine, "review-prefix-integrity")
    approval = await engine.approve(result.request_id, candidate_a.candidate_id, "reviewer-a")
    await engine.reject(result.request_id, candidate_b.candidate_id, "reviewer-b")
    trace = await engine.trace(result.request_id)
    assert trace is not None and approval.trace_revision is not None
    original = trace.entries[approval.trace_revision - 1]
    trace.entries[approval.trace_revision - 1] = TraceEntry(
        revision=original.revision,
        stage=original.stage,
        message="tampered decision",
        details=original.details,
        at=original.at,
        previous_hash=original.previous_hash,
    )

    with pytest.raises(PersistenceIntegrityError):
        await engine.lock(result.request_id, candidate_a.candidate_id, "reviewer-a")


@pytest.mark.asyncio
async def test_store_rejects_nonterminal_and_forged_replayed_decisions() -> None:
    engine = _engine()
    result, candidate_a, _ = await _recommend(engine, "review-store-integrity")
    trace = await engine.trace(result.request_id)
    assert trace is not None
    commit_revision = trace.revision
    decision_trace = trace.clone()
    decision_trace.append("human_approval", "candidate approved", {
        "candidate_id": candidate_a.candidate_id,
        "reviewer": "reviewer",
        "note": "",
        "approval_mode": ApprovalMode.STANDARD.value,
    })
    approval = engine._bound_approval(
        result,
        candidate_a,
        decision_trace,
        "reviewer",
        ApprovalStatus.APPROVED,
    )
    pending = replace(approval, status=ApprovalStatus.PENDING)
    with pytest.raises(ReviewStateConflictError, match="terminal decisions"):
        await engine.store.save_approval(
            pending,
            decision_trace,
            expected_recommendation_sha256=result.content_sha256,
            expected_trace_revision=commit_revision,
        )

    stored = await engine.store.save_approval(
        approval,
        decision_trace,
        expected_recommendation_sha256=result.content_sha256,
        expected_trace_revision=commit_revision,
    )
    forged = replace(stored, candidate_content_sha256="0" * 64)
    with pytest.raises(PersistenceIntegrityError, match="replayed decision bindings"):
        await engine.store.save_approval(
            forged,
            decision_trace,
            expected_recommendation_sha256=result.content_sha256,
            expected_trace_revision=commit_revision,
        )


@pytest.mark.asyncio
async def test_explicit_same_revision_concurrent_mutations_have_one_stale_loser() -> None:
    engine = _engine()
    result, candidate_a, candidate_b = await _recommend(engine, "review-explicit-cas")
    trace = await engine.trace(result.request_id)
    assert trace is not None
    revision = trace.revision
    outcomes = await asyncio.gather(
        engine.approve(
            result.request_id,
            candidate_a.candidate_id,
            "reviewer-a",
            expected_trace_revision=revision,
        ),
        engine.reject(
            result.request_id,
            candidate_b.candidate_id,
            "reviewer-b",
            expected_trace_revision=revision,
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ApprovalRecord) for item in outcomes) == 1
    assert sum(isinstance(item, StaleReviewRevisionError) for item in outcomes) == 1


def test_admin_review_api_uses_verified_actor_and_stable_conflicts() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app, create_app

    engine = _engine()

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "verified-reviewer", "tenant", "project",
            ("resolve:execute", "review:write", "review:lock"),
        )

    with TestClient(create_admin_app(engine=engine, authorizer=allow)) as client:
        resolved = client.post("/api/v1/resolve", json={
            "request_id": "review-api",
            "material_name": "review material",
            "quantity": 1.0,
            "quantity_unit": "kg",
            "geography": "CN",
            "year": 2025,
            "subject_type": "raw_material",
            "top_k": 2,
        })
        assert resolved.status_code == 200
        candidate_id = resolved.json()["candidates"][0]["candidate_id"]
        revision = engine.store.traces["review-api"].revision

        form_encoded = client.post(
            "/api/v1/resolutions/review-api/decisions",
            data={"candidate_id": candidate_id, "decision": "approve"},
        )
        assert form_encoded.status_code == 415

        spoofed = client.post("/api/v1/resolutions/review-api/decisions", json={
            "candidate_id": candidate_id,
            "decision": "approve",
            "reviewer": "spoofed",
        })
        assert spoofed.status_code == 422

        approved = client.post("/api/v1/resolutions/review-api/decisions", json={
            "candidate_id": candidate_id,
            "decision": "approve",
            "expected_trace_revision": revision,
        })
        assert approved.status_code == 200
        assert approved.json()["reviewer_identity"] == "verified-reviewer"

        stale = client.post("/api/v1/resolutions/review-api/locks", json={
            "candidate_id": candidate_id,
            "expected_trace_revision": revision,
        })
        assert stale.status_code == 409
        assert stale.json()["error"]["reason_code"] == "STALE_REVIEW_REVISION"

        locked = client.post("/api/v1/resolutions/review-api/locks", json={
            "candidate_id": candidate_id,
            "expected_trace_revision": revision + 1,
        })
        assert locked.status_code == 200
        assert locked.json()["reviewer_identity"] == "verified-reviewer"

        schema = client.get("/openapi.json").json()
        decision_schema = schema["components"]["schemas"]["ReviewDecisionRequestDTO"]
        assert "reviewer" not in decision_schema["properties"]
        assert "reviewer_identity" not in decision_schema["properties"]
        assert schema["paths"]["/api/v1/resolutions/{request_id}/decisions"]["post"][
            "requestBody"
        ]["content"].keys() == {"application/json"}

    public_paths = create_app(engine=_engine()).openapi()["paths"]
    assert not any(path.endswith(("/decisions", "/locks")) for path in public_paths)
