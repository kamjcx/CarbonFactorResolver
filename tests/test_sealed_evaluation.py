from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sealed_evaluation import aggregate, load_cases, load_catalog, release_gate, run_sealed


def _case(case_id: str, **changes):
    value = {
        "case_id": case_id,
        "category": "smoke",
        "request": {"material_name": "sealed steel", "quantity": 1, "quantity_unit": "kg"},
        "expected_http_status": 200,
        "expected_status": "recommendation_ready",
        "acceptable_source_ids": ["sealed-steel"],
        "forbidden_source_ids": [],
        "expected_reason_codes": [],
        "safety_dimension": "none",
    }
    value.update(changes)
    return value


def _write_jsonl(path: Path, values) -> None:
    path.write_text("\n".join(json.dumps(value) for value in values) + "\n", encoding="utf-8")


def test_loader_rejects_empty_duplicate_and_missing_cases(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="at least one"):
        load_cases(path)
    _write_jsonl(path, [_case("same"), _case("same")])
    with pytest.raises(ValueError, match="unique"):
        load_cases(path)
    _write_jsonl(path, [{"case_id": "missing"}])
    with pytest.raises(ValueError, match="lacks"):
        load_cases(path)


def test_catalog_loader_rejects_invalid_database_anchor_before_runtime(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "database": {"name": "invalid", "sha256": "bc" * 31},
        "records": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="64 lowercase hex"):
        load_catalog(path)


def test_case_loader_rejects_non_object_and_non_string_lists(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_cases(path)
    invalid = _case("invalid-list", acceptable_source_ids=[42])
    _write_jsonl(path, [invalid])
    with pytest.raises(ValueError, match="must be strings"):
        load_cases(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"database": {"sha256": "a" * 64}}, "object with records"),
        ({"records": []}, "database metadata"),
        ({"database": {"sha256": "a" * 64}, "records": [{"record_id": ""}]},
         "non-empty and unique"),
        ({"database": {"sha256": "a" * 64}, "records": [
            {"record_id": "same"}, {"record_id": "same"},
        ]}, "non-empty and unique"),
    ),
)
def test_catalog_loader_rejects_invalid_shape_and_ids(
    tmp_path: Path, payload: dict, message: str
) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_catalog(path)


def test_metric_denominators_empty_populations_and_unknown_safety_dimension() -> None:
    answerable = {
        "answerable": True,
        "passed": True,
        "safety_dimension": "unknown",
        "checks": {"top_1": True, "retrieval_recall": True, "abstention": True,
                   "forbidden_escape": True, "deterministic_replay": True},
        "observed": {"http_status": 200},
    }
    metrics = aggregate([answerable])
    assert metrics["answerable_top_1"] == 1.0
    assert metrics["abstention_correctness"] == 0.0
    assert metrics["case_contract_pass_rate"] == 1.0
    assert release_gate(metrics)["passed"] is False


def test_release_gate_rejects_partial_case_contract_even_when_aggregate_gates_pass() -> None:
    metrics = {
        "case_contract_pass_rate": 35 / 48,
        "answerable_top_1": 1.0,
        "retrieval_recall_before_gate": 1.0,
        "abstention_correctness": 1.0,
        "boundary_violation_count": 0,
        "subject_violation_count": 0,
        "unit_dimension_violation_count": 0,
        "forbidden_candidate_escape_count": 0,
        "deterministic_replay": 1.0,
        "unhandled_http_500_count": 0,
    }

    gate = release_gate(metrics)

    assert gate["passed"] is False
    assert gate["checks"]["case_contract"] is False


@pytest.mark.asyncio
async def test_runner_scores_top1_recall_abstention_forbidden_and_replay(tmp_path: Path) -> None:
    catalog = {
        "catalog_version": "sealed-test/v1",
        "database": {"name": "sealed-test", "sha256": "a" * 64},
        "records": [{
            "record_id": "sealed-steel", "name": "sealed steel", "primary_value": 1.2,
            "primary_unit": "kgCO2e/kg", "source": "Sealed synthetic", "source_id": "S-1",
            "subject_type": "raw_material", "source_quality_status": "VERIFIED",
            "admission_eligible": True, "document_status": "PUBLISHED",
            "boundary": "cradle-to-gate", "indicator": "GWP-total",
            "declared_product": "sealed steel",
            "source_document_locator": "https://example.invalid/sealed/steel",
            "source_document_sha256": "b" * 64,
        }],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(cases_path, [
        _case("hit", expected_status="reference_review_required"),
        _case(
            "miss", request={"material_name": "absent comet dust", "quantity": 1},
            expected_status="supplier_data_required", acceptable_source_ids=[],
        ),
    ])

    payload = await run_sealed(cases_path, catalog_path)
    assert payload["metrics"]["case_count"] == 2
    assert payload["schema_version"] == "cfr-sealed-evaluation/v2"
    assert payload["metrics"]["case_contract_pass_rate"] == 1.0
    assert payload["metrics"]["answerable_top_1"] == 1.0
    assert payload["metrics"]["retrieval_recall_before_gate"] == 1.0
    assert payload["metrics"]["abstention_correctness"] == 1.0
    assert payload["metrics"]["deterministic_replay"] == 1.0
    assert payload["metrics"]["unhandled_http_500_count"] == 0
    assert all(row["trace"] for row in payload["results"])
