"""Property tests for deterministic resolution and the AI suggestion boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from a1_factor_engine import (
    A1FactorResolutionEngine,
    ApprovalMode,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    MaterialCategory,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    ResolutionRequest,
    SourceQualityStatus,
    SourceRecord,
)
from a1_factor_engine.adapters import InMemoryFactorRepository
from a1_factor_engine.matching import normalize_text
from a1_factor_engine.models import (
    NormalizedActivity,
    Recommendation,
    normalized_business_fingerprint,
)
from a1_factor_engine.units import convert_mass


def _source(
    source_id: str,
    *,
    factor_value: float = 1.0,
    production_process: str = "electric arc furnace",
    source_quality_status: SourceQualityStatus = SourceQualityStatus.VERIFIED,
    admission_eligible: bool = True,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.EPD,
        provider="property-test catalogue",
        locator=f"fixture://property/{source_id}",
        material_name="steel coil",
        factor_value=factor_value,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2024,
        product_form="coil",
        composition="carbon steel",
        production_process=production_process,
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.UNKNOWN,
        source_quality_status=source_quality_status,
        admission_eligible=admission_eligible,
        indicator="GWP-total",
    )


def _request(request_id: str, **changes: object) -> ResolutionRequest:
    values: dict[str, object] = {
        "request_id": request_id,
        "material_name": "steel coil",
        "quantity": 1.0,
        "quantity_unit": "kg",
        "geography": "CN",
        "year": 2024,
        "product_form": "coil",
        "composition": "carbon steel",
        "production_process": "electric arc furnace",
        "boundary": "cradle-to-gate",
        "top_k": 5,
    }
    values.update(changes)
    return ResolutionRequest.from_mapping(values)


def _normalized_activity(
    *,
    request_id: str,
    quantity_kg: float,
    original_quantity: float,
    original_quantity_unit: str,
) -> NormalizedActivity:
    return NormalizedActivity(
        request_id=request_id,
        canonical_name="steel coil",
        aliases=(),
        quantity_kg=quantity_kg,
        geography="CN",
        year=2024,
        product_form="coil",
        composition="carbon steel",
        production_process="electric arc furnace",
        subject_type=FactorSubjectType.UNKNOWN,
        boundary="cradle-to-gate",
        target_factor_unit="kgCO2e/kg",
        original_quantity=original_quantity,
        original_quantity_unit=original_quantity_unit,
    )


def _candidate_payload(candidate: object) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "source_id": candidate.source.source_id,
        "factor_value": candidate.factor_value,
        "factor_unit": candidate.factor_unit,
        "score": candidate.score,
        "resolution_strength": candidate.resolution_strength,
        "resolution_type": candidate.resolution_type.value,
        "result_tier": candidate.result_tier.value,
        "total_emissions_kgco2e": candidate.total_emissions_kgco2e,
    }


def _decision_payload(result: Recommendation) -> dict[str, object]:
    assert result.trace is not None
    anchor = result.trace.database_anchor
    return {
        "normalized_business_fingerprint": result.trace.normalized_business_fingerprint,
        "database_anchor_identity": anchor.identity if anchor else None,
        "status": result.status.value,
        "follow_up": result.follow_up.value if result.follow_up else None,
        "candidates": tuple(_candidate_payload(item) for item in result.candidates),
        "reviewable_candidates": tuple(
            _candidate_payload(item) for item in result.reviewable_candidates
        ),
        "diagnostic_candidates": tuple(
            _candidate_payload(item) for item in result.diagnostic_candidates
        ),
        "missing_gaps": tuple(item.to_dict() for item in result.missing_gaps),
        "questions": result.questions,
    }


def _decision_fingerprint(result: Recommendation) -> str:
    raw = json.dumps(
        _decision_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@given(
    st.one_of(
        st.none(),
        st.text(st.characters(blacklist_categories=("Cs",)), max_size=160),
    )
)
def test_normalize_text_is_idempotent(raw: str | None) -> None:
    once = normalize_text(raw)
    twice = normalize_text(once.value)

    assert twice.value == once.value
    assert twice.applied_rule_ids == ()


@given(
    st.floats(
        min_value=1e-6,
        max_value=1e9,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_one_tonne_and_1000kg_are_the_same_normalized_business_input(
    quantity_t: float,
) -> None:
    quantity_kg = quantity_t * 1000.0
    from_tonnes = convert_mass(quantity_t, "t", "kg")
    from_kilograms = convert_mass(quantity_kg, "kg", "kg")
    assert from_tonnes == from_kilograms

    tonne_activity = _normalized_activity(
        request_id="tonne-run",
        quantity_kg=from_tonnes,
        original_quantity=quantity_t,
        original_quantity_unit="t",
    )
    kilogram_activity = _normalized_activity(
        request_id="kilogram-run",
        quantity_kg=from_kilograms,
        original_quantity=quantity_kg,
        original_quantity_unit="kg",
    )
    assert normalized_business_fingerprint(tonne_activity) == normalized_business_fingerprint(
        kilogram_activity
    )


@pytest.mark.asyncio
@settings(max_examples=12, deadline=None)
@given(order=st.permutations(("catalog-a", "catalog-b", "catalog-c")))
async def test_catalog_order_does_not_change_the_stable_decision(
    order: list[str],
) -> None:
    factors = {"catalog-a": 1.0, "catalog-b": 1.0, "catalog-c": 2.0}
    records = [_source(source_id, factor_value=factors[source_id]) for source_id in order]
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(records)
    ).resolve(_request("catalog-order"))

    canonical_records = [
        _source(source_id, factor_value=factors[source_id])
        for source_id in ("catalog-a", "catalog-b", "catalog-c")
    ]
    canonical = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(canonical_records)
    ).resolve(_request("catalog-order-canonical"))

    assert _decision_payload(result) == _decision_payload(canonical)


@pytest.mark.asyncio
@settings(max_examples=16, deadline=None)
@given(
    blocked_value=st.floats(
        min_value=0.0,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
    ),
    order=st.permutations(("blocked", "valid")),
)
async def test_hard_blocked_process_candidate_never_enters_a_selectable_collection(
    blocked_value: float,
    order: list[str],
) -> None:
    records_by_name = {
        "blocked": _source(
            "blocked-process",
            factor_value=blocked_value,
            production_process="basic oxygen furnace",
        ),
        "valid": _source("valid-process"),
    }
    engine = A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(
            [records_by_name[item] for item in order]
        )
    )
    result = await engine.resolve(_request("hard-process", top_k=2))

    selectable_ids = {
        item.source.source_id
        for item in (*result.candidates, *result.reviewable_candidates)
    }
    diagnostic_ids = {item.source.source_id for item in result.diagnostic_candidates}
    exclusions = result.trace.explain()["excluded_candidates"]
    blocked_exclusion = next(
        item for item in exclusions if item["source_id"] == "blocked-process"
    )

    assert "blocked-process" not in selectable_ids
    assert "blocked-process" in diagnostic_ids
    assert "unresolved_process_variant_requires_process_model" in blocked_exclusion["reasons"]
    with pytest.raises(KeyError, match="candidate not found"):
        await engine.approve(
            result.request_id,
            blocked_exclusion["candidate_id"],
            "property reviewer",
            "hard blocks are not overrideable",
            ApprovalMode.REFERENCE_OVERRIDE,
        )


@pytest.mark.asyncio
@settings(max_examples=8, deadline=None)
@given(
    first_request_id=st.uuids().map(str),
    second_request_id=st.uuids().map(str),
)
async def test_deterministic_replay_has_the_same_private_decision_fingerprint(
    first_request_id: str,
    second_request_id: str,
) -> None:
    records = [_source("replay-a", factor_value=1.0), _source("replay-b", factor_value=1.2)]
    first = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(list(records))
    ).resolve(_request(first_request_id))
    second = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository(list(records))
    ).resolve(_request(second_request_id))

    assert first.trace.raw_request_fingerprint == second.trace.raw_request_fingerprint
    assert (
        first.trace.normalized_business_fingerprint
        == second.trace.normalized_business_fingerprint
    )
    assert _decision_fingerprint(first) == _decision_fingerprint(second)


@pytest.mark.parametrize(
    "status",
    (
        RegistryRuleStatus.ACTIVE,
        RegistryRuleStatus.DEPRECATED,
        RegistryRuleStatus.REJECTED,
    ),
)
def test_runtime_rule_suggestion_rejects_every_non_draft_status(
    status: RegistryRuleStatus,
) -> None:
    with pytest.raises(ValueError, match="must remain draft"):
        RegistryRuleSuggestion(
            suggestion_id="fake:invalid-status",
            normalized_name="llm alloy x",
            status=status,
        )


class FakeLLMSuggestionPort:
    """Simulates a completion containing an out-of-contract numeric factor."""

    raw_response = {
        "proposed_aliases": ["steel coil"],
        "factor_value": 987654.0,
        "factor_unit": "kgCO2e/kg",
    }

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def suggest(self, normalized_name: str) -> RegistryRuleSuggestion:
        self.calls.append(normalized_name)
        return RegistryRuleSuggestion(
            suggestion_id="fake:semantic-only",
            normalized_name=normalized_name,
            proposed_head_material="steel",
            proposed_material_family="metals",
            proposed_category=MaterialCategory.METAL,
            proposed_aliases=("steel coil",),
            rationale="numeric completion fields were discarded at the semantic-only port",
            confidence=0.99,
        )


@pytest.mark.asyncio
async def test_fake_llm_alias_stays_draft_and_numeric_output_cannot_create_a_candidate() -> None:
    fake = FakeLLMSuggestionPort()
    result = await A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository([_source("formal-steel")]),
        rule_suggestions=fake,
    ).resolve(
        ResolutionRequest(
            request_id="fake-llm-boundary",
            material_name="llm alloy x",
            quantity=1.0,
        )
    )
    semantic = result.trace.explain()["semantic_registry"]
    suggestion = semantic["draft_suggestion"]

    assert fake.calls == ["llm alloy x"]
    assert semantic["sufficiently_identified"] is False
    assert semantic["suggestion_requires_human_review"] is True
    assert suggestion["status"] == RegistryRuleStatus.DRAFT.value
    assert suggestion["proposed_aliases"] == ("steel coil",)
    assert "factor_value" not in suggestion
    assert "factor_unit" not in suggestion
    assert not ({"factor_value", "factor_unit", "source_id", "provider", "locator"} & {
        item.name for item in fields(RegistryRuleSuggestion)
    })
    assert result.candidates == ()
    assert result.reviewable_candidates == ()
    assert result.diagnostic_candidates == ()
    assert all(
        item.source.source_id != "formal-steel"
        for item in (
            *result.candidates,
            *result.reviewable_candidates,
            *result.diagnostic_candidates,
        )
    )
