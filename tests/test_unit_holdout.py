from __future__ import annotations

import pytest

from tools.unit_holdout import (
    FROZEN_LF_SHA256,
    load_cases,
    load_catalog,
    run_holdout,
    verify_frozen_inputs,
)


def test_holdout_inputs_are_frozen_and_cover_required_risks() -> None:
    assert verify_frozen_inputs() == FROZEN_LF_SHA256
    cases = load_cases()
    catalog = load_catalog()
    coverage = {label for case in cases for label in case["coverage"]}
    assert len(cases) >= 20
    assert len(catalog["records"]) >= 10
    assert {"MASS", "ENERGY", "VOLUME", "TRANSPORT_WORK", "COUNT"} <= coverage
    assert {
        "same_dimension_scale",
        "explicit_dimension_conflict",
        "bad_request_syntax",
        "bad_catalog_unit",
        "evidence_missing",
        "versioned_evidence",
        "true_zero_hit",
        "usable_alternative",
    } <= coverage


@pytest.mark.asyncio
async def test_frozen_holdout_matches_all_predeclared_answers() -> None:
    payload = await run_holdout()
    assert payload["metrics"]["case_count"] >= 20
    assert payload["metrics"]["failed_count"] == 0, [
        row for row in payload["results"] if not row["passed"]
    ]
    assert payload["metrics"]["case_pass_rate"] == 1.0
    assert all(value == 1.0 for value in payload["metrics"]["check_accuracy"].values())
