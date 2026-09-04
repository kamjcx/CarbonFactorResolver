from __future__ import annotations

import hashlib
import json
from importlib import import_module
from pathlib import Path

import pytest

from tools.autonomous_evaluation.bad_case_audit import build_inventory
from tools.autonomous_evaluation.contracts import sha256_json
from tools.autonomous_evaluation.gates import (
    apply_quality_gate,
    load_adjudications,
    quality_exit_code,
)
from tools.autonomous_evaluation.generator import generate_bundle
from tools.portfolio_validation import dynamic_findings, portfolio_quality_gate


def failed_row(*, case_id: str = "case-1", forbidden: bool = False) -> dict[str, object]:
    request = {"material_name": "synthetic material", "quantity": 1, "quantity_unit": "kg"}
    return {
        "case_id": case_id,
        "category": "geography_conflict" if forbidden else "catalog_coverage_gap",
        "assertion_axis": "geography" if forbidden else "abstention",
        "semantic_fingerprint": "a" * 64,
        "request": request,
        "expectation": {
            "decision": "abstain",
            "status": "unresolved",
            "forbidden_ids": ["BAD"] if forbidden else [],
        },
        "observation": {
            "status": "recommendation_ready" if forbidden else "supplier_data_required",
            "primary_ids": ["BAD"] if forbidden else [],
            "reviewable_ids": [],
            "reason_codes": [],
        },
        "passed": False,
        "bad_case_category": "RANKING_FAILURE" if forbidden else "CATALOG_COVERAGE_GAP",
    }


def payload_with(row: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "test/v1",
        "generator": {"sha256": "b" * 64},
        "results": [row],
        "bad_cases": [row],
        "state_machine_attacks": [{"passed": True}],
        "metrics": {
            "hard_gates_pass": True,
            "hard_gate_results": {"zero_forbidden_escape": True},
        },
    }


def test_unresolved_bad_case_and_forbidden_escape_fail_gate_and_exit() -> None:
    payload = payload_with(failed_row(forbidden=True))
    apply_quality_gate(payload, {})
    assert payload["quality_gate"]["execution_status"] == "completed"
    assert payload["quality_gate"]["quality_status"] == "FAIL"
    assert payload["quality_gate"]["unresolved_bad_case_count"] == 1
    assert payload["quality_gate"]["unadjudicated_forbidden_escape_count"] == 1
    assert quality_exit_code(payload) == 2
    inventory = build_inventory(payload)
    assert inventory["forbidden_candidate_escape_cases"] == [
        {"case_id": "case-1", "candidate_ids": ["BAD"]}
    ]


def test_adjudication_requires_case_input_authority_and_version_bindings(tmp_path: Path) -> None:
    row = failed_row(forbidden=True)
    entry = {
        "case_id": "case-1",
        "case_sha256": "a" * 64,
        "input_sha256": sha256_json(row["request"]),
        "disposition": "accepted_limitation",
        "reason": "versioned contract difference",
        "reviewer": "maintainer",
        "authority": "ADR-1",
        "effective_version": "0.14.2",
    }
    path = tmp_path / "adjudications.json"
    path.write_text(json.dumps({
        "schema_version": "cfr-autonomous-adjudications/v1",
        "evaluator_contract_sha256": "b" * 64,
        "version": "1.0.0",
        "entries": [entry],
    }), encoding="utf-8")
    loaded = load_adjudications(
        path, generator_sha256="b" * 64, rows=[row]
    )
    assert loaded["case-1"]["authority"] == "ADR-1"
    entry["input_sha256"] = "0" * 64
    path.write_text(json.dumps({
        "schema_version": "cfr-autonomous-adjudications/v1",
        "evaluator_contract_sha256": "b" * 64,
        "version": "1.0.0",
        "entries": [entry],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="input SHA mismatch"):
        load_adjudications(path, generator_sha256="b" * 64, rows=[row])


def test_versioned_adjudications_are_bound_to_current_generated_contract() -> None:
    bundle = generate_bundle()
    rows = [
        {
            "case_id": case.case_id,
            "semantic_fingerprint": case.semantic_fingerprint,
            "request": dict(case.request),
        }
        for case in bundle.cases
    ]
    loaded = load_adjudications(
        Path("data/benchmarks/autonomous_evaluation_v1_adjudications.json"),
        generator_sha256=bundle.sha256,
        rows=rows,
    )
    assert len(loaded) == 6
    assert all(entry["reviewer"] and entry["authority"] for entry in loaded.values())


def test_valid_adjudication_is_visible_but_excluded_from_enforceable_counts() -> None:
    row = failed_row(forbidden=True)
    payload = payload_with(row)
    apply_quality_gate(payload, {"case-1": {
        "case_id": "case-1",
        "disposition": "accepted_limitation",
        "reason": "reviewed contract difference",
    }})
    assert payload["quality_gate"]["raw_bad_case_count"] == 1
    assert payload["quality_gate"]["raw_forbidden_escape_count"] == 1
    assert payload["quality_gate"]["unresolved_bad_case_count"] == 0
    assert payload["quality_gate"]["unadjudicated_forbidden_escape_count"] == 0
    assert quality_exit_code(payload) == 0


def test_committed_bad_case_audit_manifest_matches_artifacts() -> None:
    root = Path("evidence/evaluation_gate_audit/5155a68")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["artifacts"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_portfolio_gate_fails_false_quality_and_forbidden_escape() -> None:
    metrics = {
        "decision_accuracy": 0.99,
        "top_1_accuracy": 1.0,
        "recall_at_5": 1.0,
        "wrong_candidate_rate": 0.0,
        "forbidden_candidate_count": 1,
        "boundary_violation_count": 0,
        "subject_violation_count": 0,
        "unit_violation_count": 0,
        "error_count": 0,
        "more_input": {"recall": 1.0},
    }
    gate = portfolio_quality_gate(metrics)
    assert gate["execution_status"] == "completed"
    assert gate["hard_gates_pass"] is False
    assert [item["id"] for item in dynamic_findings(gate)] == [
        "CFR-PV-ZERO_FORBIDDEN_CANDIDATE_ESCAPE"
    ]


def test_ci_enforces_evaluator_process_exit_codes() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Enforce Portfolio Challenge quality gate" in workflow
    assert "Enforce autonomous public-synthetic quality gate" in workflow
    assert "Fail CI when evaluation quality gates fail" in workflow
    assert "python tools/portfolio_validation.py" in workflow
    assert "python -m tools.autonomous_evaluation" in workflow
    assert "steps.portfolio_quality.outcome" in workflow
    assert "steps.autonomous_quality.outcome" in workflow


def test_autonomous_cli_returns_nonzero_for_failed_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = import_module("tools.autonomous_evaluation.__main__")
    payload = payload_with(failed_row())

    async def fake_run_evaluation(*, seed: int) -> dict[str, object]:
        assert seed == 20260902
        return payload

    monkeypatch.setattr(cli, "run_evaluation", fake_run_evaluation)
    monkeypatch.setattr(cli, "load_adjudications", lambda *args, **kwargs: {})
    assert cli.main([]) == 2


def test_portfolio_cli_returns_nonzero_for_failed_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    portfolio = import_module("tools.portfolio_validation")

    async def fake_evaluate(*args, **kwargs) -> dict[str, object]:
        return {
            "execution_status": "completed",
            "quality_gate": {"hard_gates_pass": False},
            "runs": {},
        }

    monkeypatch.setattr(portfolio, "evaluate", fake_evaluate)
    assert portfolio.main(["--output", str(tmp_path)]) == 2
