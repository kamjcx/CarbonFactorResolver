from __future__ import annotations

import pytest

from tools.sealed_unit_holdout_v3 import (
    FROZEN_LF_SHA256,
    load_cases,
    load_catalog,
    run_holdout,
    verify_frozen_inputs,
)


def test_sealed_unit_holdout_v3_is_frozen_and_covers_post_fix_unit_risks() -> None:
    assert verify_frozen_inputs() == FROZEN_LF_SHA256
    cases = load_cases()
    catalog = load_catalog()
    coverage = {label for case in cases for label in case["coverage"]}
    assert len(cases) >= 24
    assert len(catalog["records"]) >= 13
    assert {"MASS", "ENERGY", "VOLUME", "TRANSPORT_WORK", "COUNT"} <= coverage
    assert {
        "factor_direction",
        "quantity_direction",
        "impact_scale",
        "impact_spelling",
        "conditioned_volume",
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
async def test_sealed_unit_holdout_v3_preserves_the_frozen_adjudication_failure() -> None:
    payload = await run_holdout()
    failures = [
        row for row in payload["results"] if not row["passed"]
    ]
    assert payload["metrics"]["failed_count"] == 1
    assert payload["metrics"]["passed_count"] == 23
    assert [row["case_id"] for row in failures] == ["SUH3-MASS-03"]
    assert failures[0]["checks"]["recommendation"] is True
    assert failures[0]["checks"]["status"] is True
    assert failures[0]["checks"]["factor_value"] is False
    assert failures[0]["checks"]["total_emissions"] is False
    fingerprints = [row["decision_fingerprint"] for row in payload["results"]]
    assert len(fingerprints) == len(set(fingerprints))
