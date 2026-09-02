from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from a1_factor_engine.evaluation import (
    FactorBenchCaseResult,
    FactorBenchRunner,
    aggregate_metrics,
    compare_runs,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "benchmarks" / "factorbench_v1.jsonl"
FIXTURE = ROOT / "data" / "fixtures" / "catalog" / "factorbench_catalog.json"


def _result(
    case_id: str,
    *,
    expected: tuple[str, ...] = (),
    observed: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    hard_exclusions: tuple[str, ...] = (),
    expected_status: str = "recommendation_ready",
    observed_status: str = "recommendation_ready",
    expected_identity: str | None = "mat:test",
    observed_identity: str | None = "mat:test",
    evidence: float = 1.0,
    latency: float = 1.0,
    external: bool = False,
) -> FactorBenchCaseResult:
    return FactorBenchCaseResult(
        case_id=case_id,
        tags=tags,
        expected_identity=expected_identity,
        observed_identity=observed_identity,
        expected_status=expected_status,
        observed_status=observed_status,
        expected_top_ids=expected,
        observed_top_ids=observed,
        expected_required_choices=(),
        observed_required_choices=(),
        expected_hard_exclusions=hard_exclusions,
        observed_trace_stages=("normalize", "top_k"),
        missing_trace_stages=(),
        expected_reason_codes=(),
        observed_reason_codes=(),
        evidence_coverage=evidence,
        latency_ms=latency,
        used_external_fixture=external,
    )


def test_factorbench_v1_has_frozen_schema_unique_cases_and_user_category_coverage():
    cases = load_cases(DATASET)

    assert len(cases) >= 40
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.schema_version == "factorbench/v1" for case in cases)
    assert {case.catalog_fixture for case in cases} == {
        FIXTURE.name,
        "factorbench_empty_catalog.json",
        "factorbench_extended_catalog.json",
        "factorbench_invalid_catalog.json",
    }
    tags = {tag for case in cases for tag in case.tags}
    assert {
        "exact", "alias", "multilingual", "confusable", "unit_conversion",
        "natural_mineral", "manufactured_mineral", "metal", "recycled",
        "more_input", "abstention",
    } <= tags

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["catalog_version"] == "factorbench-synthetic-catalog/v1"
    assert len(payload["records"]) >= 10
    assert all("example.invalid" in record["source_document_locator"] for record in payload["records"])


def test_core_metric_math_and_latency_percentiles():
    results = (
        _result("rank-1", expected=("a",), observed=("a", "noise"), latency=10, evidence=0.8),
        _result(
            "rank-2", expected=("b",), observed=("noise", "b"), tags=("confusable",),
            hard_exclusions=("noise",), latency=20, evidence=0.4,
        ),
        _result(
            "more-input", tags=("more_input",), expected_status="more_input_needed",
            observed_status="more_input_needed", expected_identity=None, observed_identity=None,
            evidence=0, latency=30,
        ),
        _result(
            "abstain", tags=("abstention",), expected_status="supplier_data_required",
            observed_status="supplier_data_required", expected_identity=None, observed_identity=None,
            evidence=0, latency=40,
        ),
        _result(
            "external", expected=("external",), observed=("external",), external=True,
            latency=50, evidence=1,
        ),
    )

    metrics = aggregate_metrics(results)

    assert metrics.entity_accuracy == 1.0
    assert metrics.recall_at_1 == pytest.approx(2 / 3)
    assert metrics.recall_at_3 == 1.0
    assert metrics.recall_at_5 == 1.0
    assert metrics.mrr == pytest.approx((1 + 0.5 + 1) / 3)
    assert metrics.confusable_false_positive_rate == 1.0
    assert metrics.qualified_candidate_precision == pytest.approx(3 / 5)
    assert metrics.evidence_completeness == pytest.approx((0.8 + 0.4 + 1) / 3)
    assert metrics.correct_more_input == 1.0
    assert metrics.correct_abstention == 1.0
    assert metrics.external_retrieval_success == 1.0
    assert metrics.p50_latency_ms == 30
    assert metrics.p95_latency_ms == 50


@pytest.mark.asyncio
async def test_factorbench_run_is_deterministic_and_captures_reproducibility_anchors():
    runner = FactorBenchRunner(DATASET, timer=lambda: 0.0)

    first = await runner.run()
    second = await runner.run(baseline=first)

    assert first.run_id == second.run_id
    assert first.dataset_sha256 == second.dataset_sha256
    assert first.registry_version == "material-semantic-registry/2.2.1"
    assert len(first.registry_sha256) == 64
    assert first.git_sha
    assert first.package_version == "0.14.0"
    assert len(first.catalog_anchors) == 4
    assert len(first.semantic_index_anchors) == 4
    assert first.energy_anchors == ()
    assert set(first.external_hashes) == {"fixture_external.json"}
    assert len(first.external_hashes["fixture_external.json"]) == 64
    assert first.aggregates.case_count >= 40
    assert first.aggregates.entity_accuracy == 1.0
    assert first.aggregates.recall_at_1 == 1.0
    assert first.aggregates.correct_more_input == 1.0
    # V1 remains immutable. Current admission contracts expose four historical
    # adjudication deltas: one unit-system case plus three recalled-but-rejected records.
    assert first.aggregates.correct_abstention == 5 / 9
    assert first.aggregates.external_retrieval_success == 1.0
    assert first.aggregates.evidence_completeness == 1.0
    assert all(result.error is None for result in first.results)
    assert all(not result.missing_trace_stages for result in first.results)

    stable_first = first.to_dict()
    stable_second = second.to_dict()
    stable_second["baseline_comparison"] = None
    assert stable_first == stable_second
    assert all(delta == 0.0 for delta in compare_runs(first, second).values())


@pytest.mark.asyncio
async def test_factorbench_v2_adjudicates_wrong_unit_without_changing_v1() -> None:
    v2_path = ROOT / "data" / "benchmarks" / "factorbench_v2.jsonl"
    v1_case = next(case for case in load_cases(DATASET) if case.case_id == "wrong-unit-53")
    v2_case = next(case for case in load_cases(v2_path) if case.case_id == "wrong-unit-53")

    assert v1_case.expected_status == "supplier_data_required"
    assert v1_case.expected_reason_codes == ()
    assert v2_case.expected_status == "unresolved"
    assert v2_case.expected_reason_codes == ("UNIT_DIMENSION_MISMATCH",)

    run = await FactorBenchRunner(v2_path, timer=lambda: 0.0).run()
    result = next(item for item in run.results if item.case_id == "wrong-unit-53")
    assert result.observed_status == result.expected_status == "unresolved"
    assert result.observed_reason_codes == result.expected_reason_codes == (
        "UNIT_DIMENSION_MISMATCH",
    )


@pytest.mark.asyncio
async def test_factorbench_v3_adjudicates_recalled_admission_failures() -> None:
    v2_path = ROOT / "data" / "benchmarks" / "factorbench_v2.jsonl"
    v3_path = ROOT / "data" / "benchmarks" / "factorbench_v3.jsonl"
    changed = {"wrong-indicator-54", "wrong-product-55", "wrong-boundary-56"}
    v2 = {case.case_id: case for case in load_cases(v2_path)}
    v3 = {case.case_id: case for case in load_cases(v3_path)}

    assert v2.keys() == v3.keys()
    for case_id in changed:
        assert v2[case_id].expected_status == "supplier_data_required"
        assert v3[case_id].expected_status == "unresolved"
        assert v3[case_id].expected_reason_codes == ("ADMISSION_REJECTED",)
    for case_id in v2.keys() - changed:
        assert v2[case_id] == v3[case_id]

    run = await FactorBenchRunner(v3_path, timer=lambda: 0.0).run()
    assert run.aggregates.entity_accuracy == 1.0
    assert run.aggregates.recall_at_5 == 1.0
    assert run.aggregates.correct_abstention == 1.0
    assert run.aggregates.correct_abstention == 1.0


def test_compare_runs_reports_candidate_minus_baseline():
    baseline_metrics = aggregate_metrics((_result("a", expected=("x",), observed=("x",)),))
    candidate_metrics = replace(baseline_metrics, recall_at_1=0.25, mrr=0.5)

    delta = compare_runs(
        {"aggregates": baseline_metrics.to_dict()},
        {"aggregates": candidate_metrics.to_dict()},
    )

    assert delta["recall_at_1"] == pytest.approx(-0.75)
    assert delta["mrr"] == pytest.approx(-0.5)
    assert "case_count" not in delta
