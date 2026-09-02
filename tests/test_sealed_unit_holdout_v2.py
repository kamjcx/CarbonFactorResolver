from __future__ import annotations

import pytest

from tools.sealed_unit_holdout_v2 import (
    FROZEN_LF_SHA256,
    load_cases,
    load_catalog,
    run_holdout,
    verify_frozen_inputs,
)


def test_sealed_unit_holdout_v2_inputs_are_frozen_and_cover_the_unit_contract() -> None:
    assert verify_frozen_inputs() == FROZEN_LF_SHA256
    cases = load_cases()
    catalog = load_catalog()
    coverage = {label for case in cases for label in case["coverage"]}
    assert len(cases) >= 30
    assert len(catalog["records"]) >= 15
    assert {"MASS", "ENERGY", "VOLUME", "TRANSPORT_WORK", "COUNT"} <= coverage
    assert {
        "impact_spelling",
        "impact_scale",
        "same_dimension_scale",
        "factor_direction",
        "quantity_direction",
        "explicit_dimension_conflict",
        "bad_request_syntax",
        "bad_catalog_unit",
        "evidence_missing",
        "versioned_evidence",
        "forward_direction",
        "reverse_direction",
        "true_zero_hit",
        "supplier_data_required",
        "usable_alternative",
    } <= coverage


@pytest.mark.asyncio
async def test_sealed_unit_holdout_v2_matches_every_predeclared_answer() -> None:
    payload = await run_holdout()
    assert payload["metrics"]["failed_count"] == 0, [
        row for row in payload["results"] if not row["passed"]
    ]
    assert payload["metrics"]["case_pass_rate"] == 1.0
    assert all(value == 1.0 for value in payload["metrics"]["check_accuracy"].values())
    fingerprints = [row["decision_fingerprint"] for row in payload["results"]]
    assert len(fingerprints) == len(set(fingerprints))
