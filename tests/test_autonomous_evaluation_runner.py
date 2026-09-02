from __future__ import annotations

import pytest

from tools.autonomous_evaluation.generator import generate_bundle
from tools.autonomous_evaluation.runner import (
    _case_passed,
    _metric_expectation,
    _run_case,
)


def test_case_passed_requires_status_top1_safety_and_trace() -> None:
    expected = {
        "status": "recommendation_ready",
        "acceptable_ids": ["GOOD"],
        "forbidden_ids": ["BAD"],
        "reference_only_ids": [],
        "expected_top_1": "GOOD",
    }
    observed = {
        "status": "recommendation_ready",
        "primary_ids": ["GOOD"],
        "reviewable_ids": [],
        "trace_complete": True,
    }
    assert _case_passed(expected, observed)
    assert not _case_passed(expected, {**observed, "primary_ids": ["BAD"]})
    assert not _case_passed(expected, {**observed, "trace_complete": False})


def test_metric_expectation_preserves_contract_axis() -> None:
    case = next(item for item in generate_bundle().cases if item.assertion_axis == "boundary")
    expected = _metric_expectation(case.expectation, case.assertion_axis)
    assert expected["safety_axis"] == "boundary"
    assert expected["status"] == case.expectation.status


@pytest.mark.asyncio
async def test_run_case_uses_real_engine_and_deterministic_replay() -> None:
    case = generate_bundle().cases[0]
    row, replay_equal = await _run_case(case)
    assert row["case_id"] == case.case_id
    assert row["observation"]["trace_complete"] is True
    assert replay_equal is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case_id",
    [
        "AUTO-MISSING-SPINEL",
        "AUTO-MISSING-GRID",
        "AUTO-MISSING-BAUXITE",
        "AUTO-MISSING-GRAPHITE",
    ],
)
async def test_missing_decisive_attributes_return_more_input(case_id: str) -> None:
    case = next(item for item in generate_bundle().cases if item.case_id == case_id)
    row, _ = await _run_case(case)
    assert row["observation"]["status"] == "more_input_needed"
    assert not row["observation"]["primary_ids"]
    assert row["observation"]["reviewable_ids"]


@pytest.mark.asyncio
async def test_missing_document_hash_cannot_become_primary() -> None:
    case = next(item for item in generate_bundle().cases if item.case_id == "AUTO-01-PROV-HASH")
    row, _ = await _run_case(case)
    assert not row["observation"]["primary_ids"]
    assert not row["observation"]["reviewable_ids"]
    assert "SOURCE_DOCUMENT_HASH_REQUIRED" in row["observation"]["reason_codes"]

