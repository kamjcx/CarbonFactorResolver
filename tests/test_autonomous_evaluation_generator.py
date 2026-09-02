from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tools.autonomous_evaluation import generate_bundle, materialize_catalog
from tools.autonomous_evaluation.contracts import (
    BOUNDARIES,
    BOUNDARY_COMPATIBILITY,
    EvaluationBundle,
    GeneratedCase,
)


def test_bundle_is_deterministic_unique_and_contract_sized() -> None:
    first = generate_bundle()
    second = generate_bundle()
    assert 300 <= first.case_count <= 500
    assert first.case_count == 414
    assert first.sha256 == second.sha256
    assert first.to_dict() == second.to_dict()
    assert len({case.case_id for case in first.cases}) == first.case_count
    assert len({case.semantic_fingerprint for case in first.cases}) == first.case_count


def test_seed_changes_order_variants_and_manifest() -> None:
    first = generate_bundle(seed=1)
    second = generate_bundle(seed=2)
    assert first.sha256 != second.sha256
    first_order = next(case for case in first.cases if case.category == "metamorphic_catalog_order")
    second_order = next(case for case in second.cases if case.case_id == first_order.case_id)
    assert materialize_catalog(first_order) != materialize_catalog(second_order)


def test_boundary_contract_is_exact_four_by_four() -> None:
    assert set(BOUNDARY_COMPATIBILITY) == set(BOUNDARIES)
    for requested in BOUNDARIES:
        assert set(BOUNDARY_COMPATIBILITY[requested]) == set(BOUNDARIES)
        for observed in BOUNDARIES:
            assert BOUNDARY_COMPATIBILITY[requested][observed] is (requested == observed)


def test_generated_axes_cover_required_contracts() -> None:
    bundle = generate_bundle()
    categories = {case.category for case in bundle.cases}
    axes = {case.assertion_axis for case in bundle.cases}
    assert {
        "boundary_conflict",
        "subject_conflict",
        "unit_dimension_conflict",
        "unit_same_dimension",
        "provenance_degradation",
        "source_priority_duplicate",
        "metamorphic_catalog_order",
        "metamorphic_irrelevant_noise",
        "metamorphic_quantity",
        "catalog_coverage_gap",
        "missing_decisive_attribute",
        "ineligible_high_priority",
    } <= categories
    assert {"boundary", "subject", "unit", "provenance", "source_priority"} <= axes


def test_missing_decisive_fields_require_more_input() -> None:
    cases = [
        case for case in generate_bundle().cases if case.category == "missing_decisive_attribute"
    ]
    assert len(cases) == 5
    assert all(case.expectation.status == "more_input_needed" for case in cases)
    assert all(not case.expectation.approval_allowed for case in cases)


def test_ineligible_high_priority_never_displaces_qualified_record() -> None:
    cases = [case for case in generate_bundle().cases if case.category == "ineligible_high_priority"]
    assert len(cases) == 15
    assert all(case.expectation.status == "recommendation_ready" for case in cases)
    assert all(
        case.expectation.expected_top_1 is not None
        and not case.expectation.expected_top_1.startswith("AUTO-SYN-HIGH-CONFLICT")
        for case in cases
    )


def test_catalog_and_cases_are_public_synthetic_only() -> None:
    payload = json.dumps(generate_bundle().to_dict(), ensure_ascii=False).casefold()
    forbidden = ("ecoinvent", "carbon-report", "customer", "客户", "d:\\", "c:\\users")
    assert not any(token in payload for token in forbidden)
    assert "public-synthetic" in payload
    assert "example.invalid" in payload


def test_provenance_degradation_can_only_remove_admission() -> None:
    cases = [
        case for case in generate_bundle().cases if case.category == "provenance_degradation"
    ]
    assert cases
    assert all(not case.expectation.approval_allowed for case in cases)
    assert all(case.expectation.reference_only_source_ids for case in cases)
    assert all("PROVENANCE_NOT_ADMISSIBLE" in case.expectation.reason_codes for case in cases)


def test_priority_duplicate_does_not_displace_current_record() -> None:
    cases = [
        case for case in generate_bundle().cases if case.category == "source_priority_duplicate"
    ]
    assert cases
    for case in cases:
        assert case.expectation.expected_top_1 is not None
        assert not case.expectation.expected_top_1.endswith("-HISTORICAL")


def test_semantic_duplicate_is_rejected() -> None:
    bundle = generate_bundle()
    case = bundle.cases[0]
    semantic_duplicate = replace(case, case_id=f"{case.case_id}-DUPLICATE")
    with pytest.raises(ValueError, match="semantic fingerprint"):
        EvaluationBundle(seed=bundle.seed, records=bundle.records, cases=(case, semantic_duplicate))


def test_materialized_catalog_operations_are_stable_and_non_mutating() -> None:
    bundle = generate_bundle()
    duplicate_case = next(case for case in bundle.cases if case.category == "source_priority_duplicate")
    first = materialize_catalog(duplicate_case)
    second = materialize_catalog(duplicate_case)
    assert first == second
    assert first is not second
    assert len(first["records"]) == len(bundle.records) + 1


def test_case_dict_has_parent_runner_contract() -> None:
    case: GeneratedCase = generate_bundle().cases[0]
    payload = case.to_dict()
    assert {
        "case_id",
        "category",
        "request",
        "expectation",
        "catalog_variant",
        "metamorphic_group",
        "assertion_axis",
        "semantic_fingerprint",
    } == set(payload)
