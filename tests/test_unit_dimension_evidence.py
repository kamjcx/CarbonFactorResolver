from __future__ import annotations

import json
from pathlib import Path

from tools.unit_dimension_evidence import (
    SCHEMA_VERSION,
    build_evidence,
    decision_fingerprint,
    write_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
CHALLENGE = ROOT / "data" / "benchmarks" / "portfolio_challenge_v1.jsonl"
UNIT_CASES = {
    "ENE-01": ("kWh", "kgCO2e/kWh", "pc:grid-electricity-cn", "kgCO2e/kWh"),
    "ENE-02": ("kWh", "kgCO2e/kWh", "pc:photovoltaic-electricity-cn", "kgCO2e/kWh"),
    "ENE-03": ("m3", "kgCO2e/m3", "pc:natural-gas-combustion", "kgCO2e/m3"),
    "TRN-01": ("tkm", "kgCO2e/tkm", "pc:road-freight", "kgCO2e/tkm"),
    "TRN-02": ("tkm", "kgCO2e/tkm", "pc:rail-freight", "kgCO2e/tkm"),
    "TRN-03": ("tkm", "kgCO2e/tkm", "pc:sea-freight", "kgCO2e/tkm"),
    "TRN-04": ("tkm", "kgCO2e/tkm", "pc:inland-waterway", "kgCO2e/tkm"),
    "TRN-05": ("tkm", "kgCO2e/tkm", "pc:air-freight", "kgCO2e/tkm"),
    "CNF-05": ("kWh", "kgCO2e/kg", "pc:photovoltaic-electricity-cn", "kgCO2e/kWh"),
    "CNF-06": ("kWh", "kgCO2e/kg", "pc:grid-electricity-cn", "kgCO2e/kWh"),
    "CNF-07": ("tkm", "kgCO2e/kg", "pc:rail-freight", "kgCO2e/tkm"),
    "CNF-08": ("tkm", "kgCO2e/kg", "pc:road-freight", "kgCO2e/tkm"),
}
EXPECTED_FAILURES = [
    "FIN-05",
    "ENE-01",
    "ENE-02",
    "ENE-03",
    "TRN-01",
    "TRN-02",
    "TRN-03",
    "TRN-04",
    "TRN-05",
    "CNF-05",
    "CNF-06",
    "CNF-07",
    "CNF-08",
]


def _qualification(source_id: str, *, unit_status: str, eligible: bool) -> dict[str, object]:
    value: dict[str, object] = {"source_id": source_id}
    for name in (
        "identity", "factor_kind", "subject_type", "source_quality", "indicator",
        "declared_product", "boundary",
    ):
        value[name] = {"status": "pass", "reasons": []}
    value["unit"] = {"status": unit_status, "reasons": []}
    value["eligible"] = eligible
    value["policy"] = "direct"
    value["primary_exclusion"] = None if eligible else "unit_syntax_mismatch"
    value["additional_exclusions"] = []
    return value


def _failure_trace(case_id: str, request: dict[str, object], source_id: str) -> dict[str, object]:
    is_fin = case_id == "FIN-05"
    factor_unit = "kgCO2e/kg" if is_fin else UNIT_CASES[case_id][3]
    quantity_unit = str(request.get("quantity_unit", "kg"))
    target_unit = str(request.get("target_factor_unit", "kgCO2e/kg"))
    retrieval_hits = 4 if is_fin else 1
    qualified = 1 if is_fin else 0
    required_choice = (
        {
            "field": "steel_fiber_type",
            "options": [
                "ordinary_uncoated_carbon_steel", "copper_plated_steel",
                "heat_resistant_stainless_steel", "unknown",
            ],
        }
        if is_fin
        else None
    )
    return {
        "raw_request_fingerprint": f"raw-{case_id}",
        "normalized_business_fingerprint": f"normalized-{case_id}",
        "entries": [{
            "stage": "normalize",
            "details": {
                "original_quantity_unit": quantity_unit,
                "target_factor_unit": target_unit,
            },
        }],
        "local_retrieval": {
            "records": [{"source_id": source_id, "factor_unit": factor_unit}],
        },
        "link_attempts": [{
            "strategy": "exact_link" if case_id == "TRN-03" else "synonym_link",
            "outcome": "matched",
            "candidate_source_ids": [source_id],
        }],
        "record_qualifications": [
            _qualification(source_id, unit_status="pass" if is_fin else "mismatch", eligible=is_fin)
        ],
        "candidate_admissions": [{
            "source_id": source_id,
            "retrieval_strategy": "synonym_link",
            "admitted": is_fin,
            "observation_only": not is_fin,
            "hard_exclusions": [] if is_fin else ["unit_syntax_mismatch"],
        }],
        "excluded_candidates": (
            [] if is_fin else [{"source_id": source_id, "reasons": ["unit_syntax_mismatch"]}]
        ),
        "required_choice": required_choice,
        "pipeline_funnel": {
            "raw_catalog_records": 42,
            "retrieval_hits": retrieval_hits,
            "converted_records": 42,
            "qualified_records": qualified,
            "candidate_pool": 0,
            "ranked_candidates": 0,
            "returned_candidates": 0,
        },
    }


def _portfolio_output(tmp_path: Path) -> Path:
    output = tmp_path / "portfolio"
    output.mkdir()
    challenge_rows = [
        json.loads(line) for line in CHALLENGE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = []
    for row in challenge_rows:
        case_id = row["case_id"]
        acceptable_ids = list(row.get("acceptable_ids", []))
        is_failure = case_id in EXPECTED_FAILURES
        results.append({
            "case_id": case_id,
            "request": row["request"],
            "acceptable_ids": acceptable_ids,
            "forbidden_ids": list(row.get("forbidden_ids", [])),
            "expected_decision": row["expected_decision"],
            "observed_ids": (
                [] if is_failure or row["expected_decision"] != "retrieve"
                else acceptable_ids[:1]
            ),
            "observed_status": (
                "more_input_needed" if case_id == "FIN-05"
                else "supplier_data_required" if is_failure
                else "recommendation_ready"
            ),
            "observed_decision": (
                "more_input" if case_id == "FIN-05"
                else "abstain" if is_failure or row["expected_decision"] != "retrieve"
                else "retrieve"
            ),
            "trace": (
                _failure_trace(case_id, row["request"], acceptable_ids[0])
                if is_failure else None
            ),
        })
    (output / "run_manifest.json").write_text(json.dumps({
        "commit": "80b7e864b7b75e43a29702cdae9d941fa072d3bd",
        "git_dirty": False,
    }), encoding="utf-8")
    (output / "portfolio_validation.json").write_text(json.dumps({
        "runs": {"full_cfr": {"results": results}},
    }), encoding="utf-8")
    (output / "portfolio_traces.jsonl").write_text(
        "\n".join(json.dumps({"case_id": case_id}) for case_id in EXPECTED_FAILURES) + "\n",
        encoding="utf-8",
    )
    return output


def test_before_evidence_freezes_13_failures_and_canonical_anchors(tmp_path: Path) -> None:
    evidence = build_evidence(_portfolio_output(tmp_path))

    assert evidence["schema_version"] == SCHEMA_VERSION
    assert evidence["retrieval_positive_count"] == 40
    assert evidence["observed_failed_retrieval_case_ids"] == EXPECTED_FAILURES
    assert evidence["selected_case_ids"] == EXPECTED_FAILURES
    assert evidence["selection"]["mode"] == "auto_failed_retrieval"
    assert set(evidence["artifact_sha256"]) == {
        "run_manifest.json", "portfolio_validation.json", "portfolio_traces.jsonl"
    }
    assert all(len(value) == 64 for value in evidence["artifact_sha256"].values())
    assert evidence["canonical_inputs"]["challenge"]["sha256"] == (
        "e99858e99c735ee334d1015364edf257dce12080c8e40a3d8e20acf16ab5b498"
    )
    assert evidence["canonical_inputs"]["combined_catalog_sha256"] == (
        "328e433dc39c539f231bad643478266880f34a95f630eb808e5eb114f31b90a4"
    )


def test_before_evidence_cross_checks_12_unit_cases_and_fin05(tmp_path: Path) -> None:
    evidence = build_evidence(_portfolio_output(tmp_path))
    cases = {case["case_id"]: case for case in evidence["cases"]}

    assert set(cases) == {*UNIT_CASES, "FIN-05"}
    for case_id, (quantity_unit, target_unit, source_id, factor_unit) in UNIT_CASES.items():
        case = cases[case_id]
        source = case["expected_sources"][0]
        qualification = source["qualification"]
        assert case["effective_quantity_unit"] == quantity_unit
        assert case["effective_target_factor_unit"] == target_unit
        assert case["acceptable_ids"] == [source_id]
        assert case["returned_source_ids"] == []
        assert case["observed_status"] == "supplier_data_required"
        assert source["factor_unit"] == factor_unit
        assert source["retrieval"]
        assert qualification["unit"]["status"] == "mismatch"
        assert qualification["primary_exclusion"] == "unit_syntax_mismatch"
        assert source["exclusions"][0]["reasons"] == ["unit_syntax_mismatch"]
        assert case["pipeline_funnel"] == {
            "raw_catalog_records": 42,
            "retrieval_hits": 1,
            "converted_records": 42,
            "qualified_records": 0,
            "candidate_pool": 0,
            "ranked_candidates": 0,
            "returned_candidates": 0,
        }

    fin = cases["FIN-05"]
    fin_source = fin["expected_sources"][0]
    assert fin["effective_quantity_unit"] == "kg"
    assert fin["acceptable_ids"] == ["pc:steel-fiber-product"]
    assert fin["observed_status"] == "more_input_needed"
    assert fin["required_choice"]["field"] == "steel_fiber_type"
    assert fin_source["qualification"]["eligible"] is True
    assert fin_source["qualification"]["unit"]["status"] == "pass"
    assert fin["pipeline_funnel"]["retrieval_hits"] == 4
    assert fin["pipeline_funnel"]["qualified_records"] == 1
    assert fin["pipeline_funnel"]["returned_candidates"] == 0


def test_decision_fingerprints_are_deterministic_and_before_selects_after(tmp_path: Path) -> None:
    portfolio_output = _portfolio_output(tmp_path)
    before = build_evidence(portfolio_output)
    before_path = tmp_path / "before.json"
    write_evidence(before, before_path)
    repeated = build_evidence(portfolio_output)
    after_selection = build_evidence(portfolio_output, before_evidence=before_path)

    first = {case["case_id"]: case for case in before["cases"]}
    second = {case["case_id"]: case for case in repeated["cases"]}
    assert after_selection["selected_case_ids"] == before["selected_case_ids"]
    assert after_selection["selection"]["mode"] == "before_evidence"
    for case_id, case in first.items():
        assert case["decision_fingerprint"] == second[case_id]["decision_fingerprint"]
        assert case["decision_fingerprint"] == decision_fingerprint(case["decision_payload"])
        serialized = json.dumps(case["decision_payload"], ensure_ascii=False)
        for forbidden in ("latency", "timestamp", "trace_id", "request_id", "message", "score"):
            assert forbidden not in serialized
