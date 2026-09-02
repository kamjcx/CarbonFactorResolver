from __future__ import annotations

import json

import pytest

from tools.autonomous_evaluation.metrics import (
    MetricValue,
    aggregate_metrics,
    bad_cases,
)
from tools.autonomous_evaluation.reporting import verify_manifest, write_first_run


def row(
    *,
    decision: str,
    status: str,
    acceptable: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
    primary: tuple[str, ...] = (),
    reviewable: tuple[str, ...] = (),
    safety_axis: str = "none",
    passed: bool = True,
) -> dict[str, object]:
    return {
        "case_id": f"case-{decision}-{status}-{safety_axis}",
        "category": safety_axis,
        "passed": passed,
        "expectation": {
            "decision": decision,
            "acceptable_ids": acceptable,
            "forbidden_ids": forbidden,
            "safety_axis": safety_axis,
        },
        "observation": {
            "status": status,
            "primary_ids": primary,
            "reviewable_ids": reviewable,
            "reason_codes": (),
            "evidence_complete": True,
            "trace_complete": True,
        },
    }


def test_metric_value_preserves_zero_denominator() -> None:
    assert MetricValue.of(0, 0).to_dict() == {
        "numerator": 0,
        "denominator": 0,
        "rate": None,
    }
    with pytest.raises(ValueError):
        MetricValue.of(2, 1)


def test_aggregate_metrics_separates_safety_and_question_metrics() -> None:
    rows = [
        row(
            decision="direct",
            status="recommendation_ready",
            acceptable=("good",),
            forbidden=("bad",),
            primary=("good",),
        ),
        row(
            decision="more_input",
            status="more_input_needed",
        ),
        row(
            decision="abstain",
            status="unresolved",
            forbidden=("wrong-boundary",),
            safety_axis="boundary",
        ),
        {
            "case_id": "case-http-ok",
            "category": "api_safety",
            "passed": True,
            "expectation": {"decision": "http_contract"},
            "observation": {"http_status": 200, "reason_codes": ()},
        },
    ]
    metrics = aggregate_metrics(rows, relation_results={"replay-a": True})
    assert metrics["direct_recommendation_top1"]["rate"] == 1.0
    assert metrics["recall_at_5"]["rate"] == 1.0
    assert metrics["more_input_recall"]["rate"] == 1.0
    assert metrics["abstention_correctness"]["rate"] == 1.0
    assert metrics["unnecessary_question_rate"]["numerator"] == 0
    assert metrics["boundary_violation"]["numerator"] == 0
    assert metrics["hard_gates_pass"] is True


def test_unknown_reason_code_is_reported_without_crashing() -> None:
    item = row(decision="abstain", status="unresolved")
    item["observation"]["reason_codes"] = ("NEW_UNKNOWN_REASON",)  # type: ignore[index]
    assert aggregate_metrics([item])["unknown_reason_codes"] == ["NEW_UNKNOWN_REASON"]


def test_bad_case_attribution_prefers_safety_axis() -> None:
    item = row(
        decision="abstain",
        status="recommendation_ready",
        forbidden=("unsafe",),
        primary=("unsafe",),
        safety_axis="provenance",
        passed=False,
    )
    assert bad_cases([item])[0]["bad_case_category"] == "PROVENANCE_FAILURE"


def test_first_run_manifest_is_verifiable_and_refuses_overwrite(tmp_path) -> None:
    payload = {
        "schema_version": "cfr-autonomous-evaluation-result/v1",
        "results": [row(decision="abstain", status="unresolved")],
        "metrics": aggregate_metrics([]),
        "state_machine_attacks": [],
    }
    output = tmp_path / "first-run"
    manifest = write_first_run(
        output,
        payload,
        root=tmp_path,
        generated_contract={"schema_version": "contract/v1", "cases": []},
    )
    assert manifest["schema_version"] == "cfr-autonomous-evaluation-manifest/v1"
    assert verify_manifest(output) == ()
    assert json.loads((output / "first_run.json").read_text())["schema_version"]
    with pytest.raises(FileExistsError, match="immutable"):
        write_first_run(output, payload, root=tmp_path)
