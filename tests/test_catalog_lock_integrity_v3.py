from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalRecord,
    ApprovalStatus,
    CatalogIntegrityError,
    CatalogPolicyBundle,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    PersistenceIntegrityError,
    ResolutionRequest,
    RetrievalIntent,
    SourceQualityStatus,
    SourceRecord,
)
from a1_factor_engine.adapters import (
    CatalogDatasetPolicy,
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
)
from a1_factor_engine.integrity import CATALOG_SCHEMA_VERSION, catalog_content_sha256
from a1_factor_engine.models import ResolutionTrace


def raw_record() -> dict[str, object]:
    return {
        "record_id": "factor:steel",
        "name": "steel coil",
        "primary_value": 1.2,
        "primary_unit": "kgCO2e/kg",
        "boundary": "cradle-to-gate",
        "boundary_modules": ["A1", "A2", "A3"],
        "geography": "CN",
        "year": 2025,
        "subject_type": "raw_material",
        "category": "lifecycle_factor",
        "factor_kind": "lifecycle_factor",
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "indicator": "GWP-total",
        "declared_product": "steel coil",
        "production_process": "electric arc furnace",
        "source_document_locator": "https://example.invalid/steel",
        "source_document_sha256": "a" * 64,
    }


def payload(*, declared: str | None = None) -> dict[str, object]:
    records = [raw_record()]
    actual = catalog_content_sha256(records)
    return {
        "catalog_version": "integrity-v2",
        "database": {"name": "synthetic.db", "sha256": "b" * 64},
        "manifest": {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "catalog_content_sha256": declared or actual,
            "publisher_id": "public-synthetic-test",
        },
        "records": records,
    }


def source(value: float = 1.2) -> SourceRecord:
    return SourceRecord(
        source_id="factor:steel",
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="public synthetic test",
        locator="https://example.invalid/steel",
        material_name="steel coil",
        factor_value=value,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2025,
        production_process="electric arc furnace",
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        source_quality_status=SourceQualityStatus.VERIFIED,
        admission_eligible=True,
        indicator="GWP-total",
        declared_product="steel coil",
        boundary_modules=("A1", "A2", "A3"),
        source_document_sha256="a" * 64,
    )


def request(request_id: str) -> ResolutionRequest:
    return ResolutionRequest(
        request_id=request_id,
        material_name="steel coil",
        quantity=1,
        geography="CN",
        year=2025,
        production_process="electric arc furnace",
        subject_type=FactorSubjectType.RAW_MATERIAL,
        boundary="cradle-to-gate",
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("primary_value", 12.0),
        ("primary_unit", "kgCO2e/t"),
        ("boundary", "A1"),
        ("year", 2024),
        ("geography", "GLO"),
        ("source_quality_status", "NEEDS_REVIEW"),
        ("admission_eligible", False),
        ("declared_product", "steel billet"),
        ("source_document_sha256", "c" * 64),
    ],
)
def test_catalog_digest_covers_every_decision_and_provenance_dimension(
    field: str, replacement: object
) -> None:
    baseline = raw_record()
    changed = {**baseline, field: replacement}
    assert catalog_content_sha256([baseline]) != catalog_content_sha256([changed])


def test_catalog_canonicalization_normalizes_numbers_and_unordered_fields() -> None:
    first = raw_record()
    second = {**raw_record(), "record_id": "factor:alumina", "name": "alumina"}
    first["primary_value"] = 1
    first["aliases"] = ["steel", "coil steel"]
    first["boundary_modules"] = ["A3", "A1", "A2"]
    reordered = {
        **first,
        "primary_value": 1.0,
        "aliases": ["coil steel", "steel"],
        "boundary_modules": ["A1", "A2", "A3"],
    }
    assert catalog_content_sha256([first, second]) == catalog_content_sha256(
        [second, reordered]
    )


@pytest.mark.asyncio
async def test_http_catalog_rejects_declared_content_digest_mismatch() -> None:
    repository = HttpCatalogFactorRepository(
        fetch_json=lambda _url: payload(declared="0" * 64)
    )
    with pytest.raises(CatalogIntegrityError, match="does not match actual"):
        await repository.search(RetrievalIntent("steel coil", "mat:steel"))


def test_in_memory_catalog_rejects_v2_declared_content_digest_mismatch() -> None:
    anchor = DatabaseVersionAnchor(
        "memory", "v2", "b" * 64, "memory://catalog",
        schema_version=CATALOG_SCHEMA_VERSION,
        publisher_id="test",
        catalog_content_sha256="0" * 64,
    )
    with pytest.raises(CatalogIntegrityError, match="does not match actual"):
        InMemoryFactorRepository([source()], anchor=anchor)


@pytest.mark.asyncio
async def test_in_memory_catalog_rechecks_content_on_every_search() -> None:
    repository = InMemoryFactorRepository([source()])
    repository.records[0] = source(12.0)
    with pytest.raises(CatalogIntegrityError, match="does not match actual"):
        await repository.search(RetrievalIntent("steel coil", "mat:steel"))


@pytest.mark.asyncio
async def test_dataset_policy_only_applies_to_its_exact_catalog_digest() -> None:
    catalog = payload()
    records = catalog["records"]
    assert isinstance(records, list)
    exact_digest = catalog_content_sha256(records)
    base_policy = CatalogDatasetPolicy(
        policy_id="policy:test/v1",
        record_categories=("lifecycle_factor",),
        geography="CN",
        production_approval_id="approval:test/v1",
        source_priority_rank=0,
    )
    wrong = replace(base_policy, catalog_content_sha256="f" * 64)
    exact = replace(base_policy, catalog_content_sha256=exact_digest)
    intent = RetrievalIntent("steel coil", "mat:steel")

    with pytest.raises(CatalogIntegrityError, match="legacy dataset_policies are disabled"):
        await HttpCatalogFactorRepository(
            fetch_json=lambda _url: catalog,
            dataset_policies=(base_policy, wrong),
        ).search(intent)
    with pytest.raises(CatalogIntegrityError, match="does not match the observed"):
        await HttpCatalogFactorRepository(
            fetch_json=lambda _url: catalog,
            policy_bundle=CatalogPolicyBundle(
                policy_id="deployment-policy:test-wrong/v1",
                version="1",
                approved_catalog_content_sha256="f" * 64,
                effective_from="2026-09-04",
                approved_by="test-reviewer",
                policies=(wrong,),
            ),
            policy_effective_on="2026-09-04",
        ).search(intent)
    bundle = CatalogPolicyBundle(
        policy_id="deployment-policy:test/v1",
        version="1",
        approved_catalog_content_sha256=exact_digest,
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(exact,),
        signature="test-signature",
    )
    exact_result = await HttpCatalogFactorRepository(
        fetch_json=lambda _url: catalog,
        policy_bundle=bundle,
        policy_signature_verifier=lambda _payload, _signature: True,
        policy_effective_on="2026-09-04",
    ).search(intent)

    assert exact_result.records[0].metadata["catalog_dataset_policy_ids"] == '["policy:test/v1"]'
    assert exact_result.records[0].metadata["catalog_dataset_approval_ids"] == (
        '["approval:test/v1"]'
    )
    assert exact_result.records[0].metadata["catalog_policy_bundle_content_sha256"] == (
        bundle.content_sha256
    )


@pytest.mark.asyncio
async def test_candidate_content_change_after_approval_fails_lock() -> None:
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([source()]))
    result = await engine.resolve(request("candidate-tamper"))
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer-1")
    changed = replace(candidate, factor_value=12.0, total_emissions_kgco2e=12.0)
    engine.store.recommendations[result.request_id] = replace(result, candidates=(changed,))
    with pytest.raises(ValueError, match="approval binding no longer matches"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "anchor"])
async def test_recommendation_revision_or_anchor_change_after_approval_fails_lock(
    change: str,
) -> None:
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([source()]))
    result = await engine.resolve(request(f"recommendation-{change}"))
    candidate = result.candidates[0]
    await engine.approve(result.request_id, candidate.candidate_id, "reviewer-1")
    changed = (
        replace(result, revision=result.revision + 1)
        if change == "revision"
        else replace(result, policy_anchor_sha256="f" * 64)
    )
    engine.store.recommendations[result.request_id] = changed
    with pytest.raises(ValueError, match="approval binding no longer matches"):
        await engine.lock(result.request_id, candidate.candidate_id, "reviewer-1")


@pytest.mark.asyncio
async def test_concurrent_approvals_have_one_legal_terminal_decision() -> None:
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([source()]))
    result = await engine.resolve(request("approval-race"))
    candidate_id = result.candidates[0].candidate_id
    outcomes = await asyncio.gather(
        engine.approve(result.request_id, candidate_id, "reviewer-1"),
        engine.approve(result.request_id, candidate_id, "reviewer-2"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ApprovalRecord) for item in outcomes) == 1
    assert sum(isinstance(item, Exception) for item in outcomes) == 1
    assert len(engine.store.approvals) == 1


@pytest.mark.asyncio
async def test_locked_snapshot_is_unchanged_when_live_trace_is_appended() -> None:
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([source()]))
    result = await engine.resolve(request("snapshot-immutable"))
    candidate_id = result.candidates[0].candidate_id
    await engine.approve(result.request_id, candidate_id, "reviewer-1")
    locked = await engine.lock(result.request_id, candidate_id, "reviewer-1")
    assert locked.evidence_snapshot is not None
    frozen_bytes = locked.evidence_snapshot.canonical_bytes
    frozen_sha = locked.evidence_snapshot.snapshot_sha256
    await engine._append_trace(
        result.request_id, "post_lock_note", "later live annotation", {"note": "safe"}
    )
    stored = await engine.locked(result.request_id)
    assert stored is not None and stored.evidence_snapshot is not None
    assert stored.evidence_snapshot.canonical_bytes == frozen_bytes
    assert stored.evidence_snapshot.snapshot_sha256 == frozen_sha


def test_trace_hash_chain_detects_mutation_deletion_and_reordering() -> None:
    trace = ResolutionTrace("trace:1", "request:1", "f" * 64)
    trace.append("one", "first", {"value": 1})
    trace.append("two", "second", {"value": 2})
    trace.verify_hash_chain()

    reordered = trace.clone()
    reordered.entries.reverse()
    with pytest.raises(PersistenceIntegrityError):
        reordered.verify_hash_chain()

    deleted = trace.clone()
    deleted.entries.pop(0)
    with pytest.raises(PersistenceIntegrityError):
        deleted.verify_hash_chain()

    modified = trace.clone()
    modified.entries[0] = replace(modified.entries[0], message="changed", entry_hash="")
    with pytest.raises(PersistenceIntegrityError):
        modified.verify_hash_chain()


@pytest.mark.asyncio
async def test_legacy_approval_without_digests_cannot_lock() -> None:
    engine = A1FactorResolutionEngine(local_retrieval=InMemoryFactorRepository([source()]))
    result = await engine.resolve(request("legacy-approval"))
    candidate = result.candidates[0]
    engine.store.approvals[(result.request_id, candidate.candidate_id)] = ApprovalRecord(
        result.request_id,
        candidate.candidate_id,
        "legacy-reviewer",
        ApprovalStatus.APPROVED,
    )
    with pytest.raises(ValueError, match="legacy approval without integrity digests"):
        await engine.lock(result.request_id, candidate.candidate_id, "legacy-reviewer")
