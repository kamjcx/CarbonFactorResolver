from __future__ import annotations

import pytest

from tools.sealed_unit_holdout_v4 import (
    FROZEN_LF_SHA256,
    load_cases,
    load_catalog,
    run_holdout,
    verify_frozen_inputs,
)


def test_sealed_unit_holdout_v4_is_frozen_and_covers_the_complete_unit_contract() -> None:
    assert verify_frozen_inputs() == FROZEN_LF_SHA256
    cases = load_cases()
    catalog = load_catalog()
    coverage = {label for case in cases for label in case["coverage"]}
    assert len(cases) >= 21
    assert len(catalog["records"]) >= 13
    assert {"MASS", "ENERGY", "VOLUME", "TRANSPORT_WORK", "COUNT"} <= coverage
    assert {
        "factor_direction",
        "quantity_direction",
        "impact_scale",
        "impact_spelling",
        "reverse_regression",
        "no_automatic_equivalence",
        "scaled_conditioned_volume",
        "explicit_dimension_conflict",
        "bad_request_syntax",
        "bad_catalog_unit",
        "true_zero_hit",
        "supplier_data_required",
    } <= coverage


@pytest.mark.asyncio
async def test_sealed_unit_holdout_v4_matches_every_frozen_answer() -> None:
    payload = await run_holdout()
    assert payload["metrics"]["failed_count"] == 0, [
        row for row in payload["results"] if not row["passed"]
    ]
    assert payload["metrics"]["case_pass_rate"] == 1.0
    assert all(value == 1.0 for value in payload["metrics"]["check_accuracy"].values())
    fingerprints = [row["decision_fingerprint"] for row in payload["results"]]
    assert len(fingerprints) == len(set(fingerprints))
