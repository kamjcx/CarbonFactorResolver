from __future__ import annotations

from dataclasses import replace

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    CatalogPolicyBundle,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    LinkStrategy,
    ResolutionRequest,
    ResolutionStatus,
    ResultTier,
    SourceRecord,
)
from a1_factor_engine.adapters import (
    CatalogDatasetPolicy,
    HttpCatalogFactorRepository,
    InMemoryFactorRepository,
)
from a1_factor_engine.integrity import catalog_content_sha256
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import DatabaseVersionAnchor
from a1_factor_engine.semantic_index import SemanticFactorIndex
from a1_factor_engine.serialization import to_jsonable


def source(
    source_id: str,
    name: str,
    *,
    factor_kind: FactorKind = FactorKind.LIFECYCLE_FACTOR,
    subject_type: FactorSubjectType = FactorSubjectType.ENERGY,
    geography: str | None = "CN",
    year: int | None = 2025,
    value: float = 0.4,
    unit: str = "kgCO2e/kWh",
    declared_product: str | None = None,
    priority: int = 100,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="rc3 synthetic",
        locator=f"https://example.invalid/{source_id}",
        material_name=name,
        factor_value=value,
        factor_unit=unit,
        geography=geography,
        year=year,
        boundary="cradle-to-gate",
        factor_kind=factor_kind,
        subject_type=subject_type,
        indicator="GWP-total",
        declared_product=declared_product or name,
        boundary_modules=("A1", "A2", "A3"),
        metadata={
            "match_strategy": LinkStrategy.EXACT.value,
            "source_priority_rank": str(priority),
        },
        source_document_sha256="ab" * 32,
    )


@pytest.mark.parametrize(
    ("factor_kind", "subject_type", "quantity_unit"),
    (
        (FactorKind.ENERGY_FACTOR, FactorSubjectType.ENERGY, "kWh"),
        (FactorKind.COMBUSTION_FACTOR, FactorSubjectType.ENERGY, "kWh"),
        (FactorKind.TRANSPORT_FACTOR, FactorSubjectType.TRANSPORT, "tkm"),
    ),
)
@pytest.mark.asyncio
async def test_operational_factor_kinds_are_admitted_only_for_explicit_matching_subject(
    factor_kind: FactorKind,
    subject_type: FactorSubjectType,
    quantity_unit: str,
) -> None:
    unit = "kgCO2e/tkm" if subject_type == FactorSubjectType.TRANSPORT else "kgCO2e/kWh"
    record = source(
        f"operational-{factor_kind.value}",
        "rc3 freight" if subject_type == FactorSubjectType.TRANSPORT else "rc3 electricity",
        factor_kind=factor_kind,
        subject_type=subject_type,
        unit=unit,
    )
    request = ResolutionRequest(
        material_name=record.material_name,
        quantity=1,
        quantity_unit=quantity_unit,
        subject_type=subject_type,
        geography="CN",
        year=2025,
    )

    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((record,))
    ).resolve(request)

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].source.source_id == record.source_id
    assert result.candidates[0].result_tier == ResultTier.PRIMARY_RECOMMENDATION


@pytest.mark.asyncio
async def test_operational_factor_without_request_subject_returns_more_input() -> None:
    record = source(
        "operational-needs-subject",
        "rc3 electricity",
        factor_kind=FactorKind.ENERGY_FACTOR,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((record,))
    ).resolve(ResolutionRequest(
        material_name=record.material_name,
        quantity=1,
        quantity_unit="kWh",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.reason_codes == ()
    assert result.trace.explain()["required_choice"] == {
        "field": "subject_type",
        "options": ("energy",),
    }


@pytest.mark.asyncio
async def test_lifecycle_energy_factor_without_request_subject_returns_more_input() -> None:
    record = source("lifecycle-needs-subject", "lifecycle electricity")
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((record,))
    ).resolve(ResolutionRequest(
        material_name=record.material_name,
        quantity=1,
        quantity_unit="kWh",
    ))

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    assert result.reason_codes == ()
    assert result.trace.explain()["required_choice"]["field"] == "subject_type"


@pytest.mark.asyncio
async def test_recalled_hard_ineligible_record_is_unresolved_not_zero_hit() -> None:
    record = source(
        "wrong-subject",
        "rc3 electricity",
        factor_kind=FactorKind.ENERGY_FACTOR,
        subject_type=FactorSubjectType.TRANSPORT,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((record,))
    ).resolve(ResolutionRequest(
        material_name=record.material_name,
        quantity=1,
        quantity_unit="kWh",
        subject_type=FactorSubjectType.ENERGY,
    ))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert "ADMISSION_REJECTED" in result.reason_codes
    assert result.trace.explain()["record_qualifications"][0]["primary_exclusion"] == (
        "subject_type_mismatch"
    )


@pytest.mark.asyncio
async def test_explicit_geography_and_year_conflicts_are_hard_rejected() -> None:
    cn = source("cn-electricity", "rc3 electricity", geography="CN", year=2024, priority=100)
    preferred_us = source(
        "us-electricity", "rc3 electricity", geography="US", year=2025, priority=0,
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((preferred_us, cn))
    ).resolve(ResolutionRequest(
        material_name="rc3 electricity",
        quantity=1,
        quantity_unit="kWh",
        subject_type=FactorSubjectType.ENERGY,
        geography="CN",
        year=2025,
        top_k=2,
    ))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.candidates == ()
    exclusions = result.trace.explain()["excluded_candidates"]
    reasons = {reason for item in exclusions for reason in item["reasons"]}
    assert {"geography_mismatch", "year_mismatch"} <= reasons


@pytest.mark.asyncio
async def test_far_year_is_rejected_while_missing_year_remains_unknown() -> None:
    cases = (
        (source("stale-electricity", "stale electricity", year=2015), ResolutionStatus.UNRESOLVED),
        (source("undated-electricity", "undated electricity", year=None), ResolutionStatus.RECOMMENDATION_READY),
    )
    for record, expected_status in cases:
        result = await A1FactorResolutionEngine(
            local_retrieval=InMemoryFactorRepository((record,))
        ).resolve(ResolutionRequest(
            material_name=record.material_name,
            quantity=1,
            quantity_unit="kWh",
            subject_type=FactorSubjectType.ENERGY,
            geography="CN",
            year=2025,
        ))
        assert result.status == expected_status
        if record.year is None:
            assert result.candidates[0].result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS
        else:
            assert result.candidates == ()


@pytest.mark.asyncio
async def test_catalog_maps_operational_factor_kinds() -> None:
    payload = {
        "catalog_version": "rc3",
        "database": {"name": "rc3", "sha256": "cd" * 32},
        "records": [{
            "record_id": "energy-1",
            "category": "energy_factor",
            "name": "rc3 electricity",
            "primary_value": 0.4,
            "primary_unit": "kgCO2e/kWh",
            "source": "synthetic",
            "subject_type": "energy",
            "source_quality_status": "VERIFIED",
            "admission_eligible": True,
            "indicator": "GWP-total",
            "declared_product": "rc3 electricity",
            "boundary": "cradle-to-gate",
            "boundary_modules": ["A1", "A2", "A3"],
        }],
    }
    repository = HttpCatalogFactorRepository(fetch_json=lambda _url: payload)
    intent = DEFAULT_MATERIAL_REGISTRY.resolve("rc3 electricity").retrieval_intent
    assert intent is not None

    records = (await repository.search(intent)).records
    assert records[0].factor_kind == FactorKind.ENERGY_FACTOR


def test_semantic_index_digest_covers_decision_fields() -> None:
    anchor = DatabaseVersionAnchor(
        catalog_name="rc3",
        catalog_version="1",
        database_sha256="ef" * 32,
        locator="memory://rc3",
    )
    first = source("digest", "digest electricity", value=0.4)
    changed = replace(first, factor_value=0.5)

    first_index = SemanticFactorIndex((first,), anchor, DEFAULT_MATERIAL_REGISTRY)
    changed_index = SemanticFactorIndex((changed,), anchor, DEFAULT_MATERIAL_REGISTRY)

    assert first_index.anchor.index_version != changed_index.anchor.index_version


@pytest.mark.asyncio
async def test_conflicting_duplicate_local_source_ids_fail_closed() -> None:
    first = source("duplicate-local", "duplicate electricity", value=0.4)
    second = replace(first, factor_value=0.8)
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((first, second))
    ).resolve(ResolutionRequest(
        material_name=first.material_name,
        quantity=1,
        quantity_unit="kWh",
        subject_type=FactorSubjectType.ENERGY,
    ))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.candidates == ()
    assert result.reason_codes == ("CONFLICTING_DUPLICATE_SOURCE_ID",)
    retrieval = result.trace.latest("local_retrieval")
    assert retrieval is not None
    assert retrieval.details["reason_code"] == "CONFLICTING_DUPLICATE_SOURCE_ID"


@pytest.mark.asyncio
async def test_http_catalog_cache_rebuilds_when_payload_changes_under_same_anchor() -> None:
    record = {
        "record_id": "cache-energy",
        "category": "energy_factor",
        "name": "cache electricity",
        "primary_value": 0.4,
        "primary_unit": "kgCO2e/kWh",
        "source": "synthetic",
        "subject_type": "energy",
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "indicator": "GWP-total",
        "declared_product": "cache electricity",
        "boundary": "cradle-to-gate",
        "boundary_modules": ["A1", "A2", "A3"],
    }
    payload = {
        "catalog_version": "rc3",
        "database": {"name": "rc3", "sha256": "cd" * 32},
        "records": [record],
    }
    repository = HttpCatalogFactorRepository(fetch_json=lambda _url: payload)
    intent = DEFAULT_MATERIAL_REGISTRY.resolve("cache electricity").retrieval_intent
    assert intent is not None

    first = await repository.search(intent)
    record["primary_value"] = 0.5
    second = await repository.search(intent)

    assert first.records[0].factor_value == 0.4
    assert second.records[0].factor_value == 0.5
    assert first.semantic_index_anchor != second.semantic_index_anchor


@pytest.mark.asyncio
async def test_http_catalog_cache_rebuilds_when_decision_policy_changes() -> None:
    payload = {
        "catalog_version": "rc3",
        "database": {"name": "rc3", "sha256": "cd" * 32},
        "records": [{
            "record_id": "policy-cache-energy",
            "category": "energy_factor",
            "name": "policy cache electricity",
            "primary_value": 0.4,
            "primary_unit": "kgCO2e/kWh",
            "source": "synthetic",
            "subject_type": "energy",
            "source_quality_status": "VERIFIED",
            "admission_eligible": True,
            "indicator": "GWP-total",
            "declared_product": "policy cache electricity",
            "boundary": "cradle-to-gate",
            "boundary_modules": ["A1", "A2", "A3"],
        }],
    }
    policy_cn = CatalogDatasetPolicy(
        policy_id="same-policy-id",
        record_categories=("energy_factor",),
        geography="CN",
        year=2024,
        catalog_content_sha256=catalog_content_sha256(payload["records"]),
    )
    repository = HttpCatalogFactorRepository(
        fetch_json=lambda _url: payload,
        policy_bundle=CatalogPolicyBundle(
            policy_id="deployment-policy:cache/v1",
            version="1",
            approved_catalog_content_sha256=catalog_content_sha256(payload["records"]),
            effective_from="2026-09-04",
            approved_by="test-reviewer",
            policies=(policy_cn,),
        ),
    )
    intent = DEFAULT_MATERIAL_REGISTRY.resolve("policy cache electricity").retrieval_intent
    assert intent is not None

    first = await repository.search(intent)
    repository.policy_bundle = CatalogPolicyBundle(
        policy_id="deployment-policy:cache/v2",
        version="2",
        approved_catalog_content_sha256=catalog_content_sha256(payload["records"]),
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(replace(policy_cn, geography="US", year=2025),),
    )
    second = await repository.search(intent)

    assert (first.records[0].geography, first.records[0].year) == ("CN", 2024)
    assert (second.records[0].geography, second.records[0].year) == ("US", 2025)
    assert first.semantic_index_anchor != second.semantic_index_anchor


def test_json_serializer_sorts_unordered_containers() -> None:
    assert to_jsonable(frozenset({"z", "a", "m"})) == ["a", "m", "z"]


class _ExternalConnector:
    def __init__(self, value: float) -> None:
        self.value = value

    async def discover(self, _intent):
        return ({"source_id": "external-energy", "value": self.value},)

    async def fetch(self, reference):
        return {
            "source_id": reference["source_id"],
            "value": reference["value"],
            "content_sha256": f"{int(reference['value'] * 100):064d}"[-64:],
        }

    def health(self):
        return {"status": "ok"}


class _ExternalExtractor:
    async def extract(self, document, _intent):
        return (source(
            str(document["source_id"]),
            "external electricity",
            value=float(document["value"]),
        ),)


@pytest.mark.asyncio
async def test_external_records_use_the_same_qualification_and_admission_trace() -> None:
    result = await A1FactorResolutionEngine(
        external_connectors=(_ExternalConnector(0.4),),
        external_extractor=_ExternalExtractor(),
    ).resolve(ResolutionRequest(
        material_name="external electricity",
        quantity=1,
        quantity_unit="kWh",
        subject_type=FactorSubjectType.ENERGY,
    ))

    explanation = result.trace.explain()
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert explanation["record_qualifications"][0]["source_id"] == "external-energy"
    assert explanation["candidate_admissions"][0] == {
        "source_id": "external-energy",
        "retrieval_strategy": "exact_link",
        "admitted": True,
        "observation_only": False,
        "identity_proof_ids": ("energy.electricity/v1",),
        "source_identity_rule_ids": ("energy.electricity/v1",),
        "hard_exclusions": (),
    }


@pytest.mark.asyncio
async def test_conflicting_duplicate_external_source_ids_fail_closed() -> None:
    result = await A1FactorResolutionEngine(
        external_connectors=(_ExternalConnector(0.4), _ExternalConnector(0.8)),
        external_extractor=_ExternalExtractor(),
    ).resolve(ResolutionRequest(
        material_name="external electricity",
        quantity=1,
        quantity_unit="kWh",
        subject_type=FactorSubjectType.ENERGY,
    ))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.candidates == ()
    assert result.reason_codes == ("CONFLICTING_DUPLICATE_SOURCE_ID",)
    assert any(
        item["source_id"] == "external-energy"
        and "conflicting_duplicate_source_id" in item["reasons"]
        for item in result.trace.explain()["excluded_candidates"]
    )


@pytest.mark.asyncio
async def test_exact_unknown_name_cannot_bypass_incompatible_declared_product() -> None:
    record = source(
        "unknown-exact",
        "foo material",
        subject_type=FactorSubjectType.RAW_MATERIAL,
        unit="kgCO2e/kg",
        declared_product="not foo material waste",
    )
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((record,))
    ).resolve(ResolutionRequest(
        material_name="foo material",
        quantity=1,
        quantity_unit="kg",
        subject_type=FactorSubjectType.RAW_MATERIAL,
    ))

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.candidates == ()
    assert result.reason_codes == ("ADMISSION_REJECTED",)
    qualification = result.trace.explain()["record_qualifications"][0]
    assert qualification["declared_product"]["status"] == "mismatch"
