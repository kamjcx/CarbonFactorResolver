from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

from tools.portfolio_validation import (
    aggregate,
    combined_catalog,
    evaluate,
    load_cases,
    metric_prf,
    predicted_decision,
)

ROOT = Path(__file__).resolve().parents[1]
CHALLENGE = ROOT / "data" / "benchmarks" / "portfolio_challenge_v1.jsonl"
CATALOGS = (
    ROOT / "data" / "fixtures" / "catalog" / "factorbench_catalog.json",
    ROOT / "data" / "fixtures" / "catalog" / "factorbench_extended_catalog.json",
    ROOT / "data" / "fixtures" / "catalog" / "portfolio_catalog_additions.json",
)


def file_sha(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def test_frozen_factorbench_and_holdout_are_unchanged() -> None:
    assert file_sha(ROOT / "data" / "benchmarks" / "factorbench_v1.jsonl") == (
        "769e8abcab9b79d6c1a1eefe444c4b35c4286d186254661c8fd2e13f14a0e796"
    )
    assert file_sha(ROOT / "data" / "benchmarks" / "real_query_holdout_v1.jsonl") == (
        "d44e63e3123b564129b922b57096f3c93bf1928c99d12cc9d02637188c3d13c2"
    )
    assert file_sha(CHALLENGE) == (
        "e99858e99c735ee334d1015364edf257dce12080c8e40a3d8e20acf16ab5b498"
    )
    assert file_sha(ROOT / "data" / "fixtures" / "catalog" / "portfolio_catalog_additions.json") == (
        "d19b44dfccce7d7d0021c65d5d37214a2d9738a855d8a40b6258836f7fbdef7c"
    )


def test_portfolio_challenge_has_the_frozen_balanced_shape() -> None:
    cases = load_cases(CHALLENGE)
    counts = {category: sum(case.category == category for case in cases) for category in {
        case.category for case in cases
    }}
    assert len(cases) == 60
    assert counts == {
        "raw_material_positive": 10,
        "finished_product_positive": 5,
        "energy_positive": 5,
        "transport_positive": 5,
        "process_positive": 5,
        "confusable": 10,
        "more_input": 10,
        "abstention": 10,
    }
    assert len(combined_catalog(CATALOGS)["records"]) == 42


def test_three_way_portfolio_evaluation_is_real_and_safety_sensitive(tmp_path: Path) -> None:
    result = asyncio.run(evaluate(CHALLENGE, CATALOGS, tmp_path))
    assert set(result["runs"]) == {"exact_alias", "lexical", "full_cfr"}
    assert (tmp_path / "portfolio_validation.json").is_file()
    assert (tmp_path / "portfolio_validation.csv").is_file()
    for name in (
        "run_manifest.json", "portfolio_traces.jsonl", "REPORT_EN.md", "REPORT_ZH.md",
        "retrieval_quality.svg", "safety_rates.svg", "latency_percentiles.svg",
    ):
        assert (tmp_path / name).is_file(), name
    full = result["runs"]["full_cfr"]["metrics"]
    lexical = result["runs"]["lexical"]["metrics"]
    assert {finding["id"] for finding in result["known_findings"]} == {
        "CFR-PV-001", "CFR-PV-002", "CFR-PV-003"
    }
    assert all(finding["status"] == "OPEN" for finding in result["known_findings"])
    assert full["wrong_candidate_rate"] == 6 / 46
    assert full["wrong_candidate_count"] == 6
    assert full["returned_candidate_count"] == 46
    assert full["top_1_correct_count"] == 40
    assert full["boundary_violation_rate"] == 0
    assert full["subject_violation_rate"] == 0
    assert lexical["recall_at_5"] >= full["recall_at_5"]
    assert lexical["wrong_candidate_rate"] > full["wrong_candidate_rate"]
    assert lexical["subject_violation_rate"] > 0
    trace_rows = [json.loads(line) for line in (tmp_path / "portfolio_traces.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    assert len(trace_rows) == 60
    assert {row["case_id"] for row in trace_rows} == {
        row["case_id"] for row in result["runs"]["full_cfr"]["results"]
    }
    with (tmp_path / "portfolio_validation.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    full_rows = [row for row in csv_rows if row["method"] == "full_cfr" and row["candidate_id"]]
    assert len(full_rows) == full["returned_candidate_count"]
    assert sum(row["classification"] != "acceptable" for row in full_rows) == full["wrong_candidate_count"]
    unit_expected = {
        "ENE-01": "pc:grid-electricity-cn",
        "ENE-02": "pc:photovoltaic-electricity-cn",
        "ENE-03": "pc:natural-gas-combustion",
        "TRN-01": "pc:road-freight",
        "TRN-02": "pc:rail-freight",
        "TRN-03": "pc:sea-freight",
        "TRN-04": "pc:inland-waterway",
        "TRN-05": "pc:air-freight",
        "CNF-05": "pc:photovoltaic-electricity-cn",
        "CNF-06": "pc:grid-electricity-cn",
        "CNF-07": "pc:rail-freight",
        "CNF-08": "pc:road-freight",
    }
    by_case = {row["case_id"]: row for row in result["runs"]["full_cfr"]["results"]}
    assert all(
        by_case[case_id]["observed_decision"] == "retrieve"
        and source_id in by_case[case_id]["observed_ids"]
        for case_id, source_id in unit_expected.items()
    )
    assert by_case["FIN-05"]["observed_status"] == "more_input_needed"
    assert by_case["FIN-05"]["observed_ids"] == ["pc:steel-fiber-product"]
    top_k = by_case["FIN-05"]["trace"]["entries"][-1]["details"]
    assert top_k["selected_candidate_ids"] == []
    assert top_k["reviewable_candidate_ids"] == ["local:pc:steel-fiber-product"]
    assert top_k["required_fields"] == ["steel_fiber_type"]


def test_error_is_not_counted_as_abstention() -> None:
    assert predicted_decision((), "error") == "error"
    metric = metric_prf([True], [predicted_decision((), "error") == "abstain"])
    assert metric["true_positive"] == 0
    assert metric["false_negative"] == 1


def test_aggregate_scores_negative_case_candidates_and_empty_populations() -> None:
    records = {
        "bad": {"record_id": "bad", "subject_type": "finished_product", "boundary": "A3"}
    }
    negative_row = {
        "case_id": "negative", "request": {"subject_type": "raw_material", "boundary": "A1"},
        "expected_decision": "abstain", "observed_decision": "retrieve", "observed_ids": ["bad"],
        "acceptable_ids": [], "forbidden_ids": ["bad"], "latency_ms": 1.0,
    }
    metric = aggregate([negative_row], records)
    assert metric["wrong_candidate_count"] == 1
    assert metric["forbidden_candidate_count"] == 1
    assert metric["wrong_candidate_rate"] == 1.0
    assert metric["boundary_violation_rate"] == 1.0
    assert metric["subject_violation_rate"] == 1.0
    assert metric["top_1_accuracy"] is None
    assert metric["recall_at_5"] is None
    assert metric["mrr"] is None
    assert metric["p50_latency_ms"] <= metric["p95_latency_ms"] <= metric["p99_latency_ms"]


def test_aggregate_rejects_unknown_candidate_ids() -> None:
    row = {
        "case_id": "unknown", "request": {}, "expected_decision": "abstain",
        "observed_decision": "retrieve", "observed_ids": ["missing"],
        "acceptable_ids": [], "forbidden_ids": [], "latency_ms": 0.0,
    }
    try:
        aggregate([row], {})
    except ValueError as exc:
        assert "unknown candidate ID" in str(exc)
    else:
        raise AssertionError("unknown candidate ID must fail closed")
