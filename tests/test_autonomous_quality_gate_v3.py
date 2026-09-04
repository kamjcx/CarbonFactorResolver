from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.autonomous_evaluation.contracts import sha256_json
from tools.autonomous_evaluation.gates import (
    DEFAULT_ADJUDICATIONS,
    _expectation_satisfied,
    apply_quality_gate,
    load_adjudications,
)
from tools.autonomous_evaluation.generator import generate_bundle
from tools.autonomous_evaluation.metrics import aggregate_metrics
from tools.autonomous_evaluation.runner import SCHEMA_VERSION as RUN_SCHEMA_VERSION
from tools.autonomous_evaluation.v3_contract import (
    _metric_expectation,
    build_adjudications,
    build_freeze_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
ADJUDICATIONS = ROOT / "data/benchmarks/autonomous_evaluation_v3_adjudications.json"
FREEZE = ROOT / "data/benchmarks/autonomous_evaluation_v3_freeze.json"


def _sha(path: Path) -> str:
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def test_v1_and_v2_history_remain_byte_identical() -> None:
    assert _sha(ROOT / "data/benchmarks/autonomous_evaluation_v1_adjudications.json") == (
        "a7ad96a4b6a25678c003227231c0b95ea9aec8175225433cd9c57322a60da43f"
    )
    assert _sha(ROOT / "data/benchmarks/autonomous_evaluation_v2_adjudications.json") == (
        "de10a296206faeec27b1f323e4cc5ec65ad85749e343e9d2e0dd321583831f18"
    )


def test_v3_generated_artifacts_match_the_committed_freeze() -> None:
    adjudications = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert adjudications == build_adjudications()
    assert freeze == build_freeze_manifest(ROOT)
    assert DEFAULT_ADJUDICATIONS == Path(
        "data/benchmarks/autonomous_evaluation_v3_adjudications.json"
    )
    assert RUN_SCHEMA_VERSION == "cfr-autonomous-evaluation-run/v2"
    assert adjudications["version"] == "3.0.0"
    assert adjudications["historical_results_rewritten"] is False
    assert len(adjudications["entries"]) == 103
    assert freeze["generated_case_count"] == 414
    assert freeze["api_case_count"] == 4
    assert freeze["total_case_count"] == 418
    unsigned = {key: value for key, value in freeze.items() if key != "manifest_sha256"}
    assert freeze["manifest_sha256"] == sha256_json(unsigned)
    assert len({item["case_sha256"] for item in freeze["generated_cases"]}) == 414


def test_v3_adjudications_bind_every_case_and_input_sha() -> None:
    bundle = generate_bundle()
    rows = [
        {
            "case_id": case.case_id,
            "semantic_fingerprint": case.semantic_fingerprint,
            "request": dict(case.request),
            "expectation": _metric_expectation(case),
        }
        for case in bundle.cases
    ]
    loaded = load_adjudications(
        ADJUDICATIONS,
        generator_sha256=bundle.sha256,
        rows=rows,
    )
    assert len(loaded) == 103
    causes: dict[str, int] = {}
    for entry in loaded.values():
        cause = str(entry["root_cause"])
        causes[cause] = causes.get(cause, 0) + 1
        assert entry["previous_expectation"] != entry["effective_expectation"]
        assert entry["effective_expectation"]["approval_allowed"] is False
    assert causes == {
        "catalogue_alias_identity_authority": 16,
        "catalogue_coverage_status_vocabulary": 12,
        "input_gap_before_subject_terminal_status": 1,
        "provenance_fail_closed_status": 60,
        "steel_fibre_decisive_attribute": 13,
        "unresolved_alias_decisive_identity": 1,
    }


def test_provenance_adjudications_never_allow_a_selectable_candidate() -> None:
    payload = build_adjudications()
    entries = [
        item
        for item in payload["entries"]
        if item["root_cause"] == "provenance_fail_closed_status"
    ]
    assert len(entries) == 60
    assert {item["case_id"].rsplit("-", 1)[1] for item in entries} == {
        "HASH",
        "QUALITY",
        "ELIGIBLE",
    }
    for entry in entries:
        effective = entry["effective_expectation"]
        assert effective["acceptable_ids"] == []
        assert effective["reference_only_ids"] == []
        assert effective["forbidden_ids"]
        assert effective["approval_allowed"] is False


def test_effective_contract_is_verified_not_blindly_exempted() -> None:
    request = {"material_name": "synthetic", "quantity": 1, "quantity_unit": "kg"}
    raw_expectation = {
        "decision": "direct",
        "status": "recommendation_ready",
        "acceptable_ids": ["SOURCE"],
        "forbidden_ids": [],
        "reference_only_ids": [],
        "reason_codes": [],
        "expected_top_1": "SOURCE",
        "approval_allowed": True,
        "safety_axis": None,
    }
    observation = {
        "status": "reference_review_required",
        "primary_ids": [],
        "reviewable_ids": ["SOURCE"],
        "diagnostic_ids": [],
        "reason_codes": [],
        "trace_complete": True,
        "evidence_complete": True,
        "error": False,
    }
    row = {
        "case_id": "case-1",
        "category": "positive_reviewed-alias",
        "assertion_axis": "alias_or_entity",
        "semantic_fingerprint": "a" * 64,
        "request": request,
        "expectation": raw_expectation,
        "observation": observation,
        "passed": False,
    }
    metrics = aggregate_metrics([row], relation_results={"replay:case-1": True})
    payload = {
        "generator": {"sha256": "b" * 64},
        "results": [row],
        "bad_cases": [row],
        "relation_results": {"replay:case-1": True},
        "state_machine_attacks": [{"passed": True}],
        "metrics": metrics,
    }
    effective = {
        **raw_expectation,
        "decision": "reference_review",
        "status": "reference_review_required",
        "acceptable_ids": [],
        "reference_only_ids": ["SOURCE"],
        "expected_top_1": None,
        "approval_allowed": False,
    }
    entry = {"case_id": "case-1", "effective_expectation": effective}
    apply_quality_gate(payload, {"case-1": entry})
    assert payload["metrics"]["direct_recommendation_top1"]["denominator"] == 1
    assert payload["effective_metrics"]["direct_recommendation_top1"]["denominator"] == 0
    assert payload["quality_gate"]["unresolved_bad_case_count"] == 0

    bad_observation = {**observation, "reviewable_ids": ["FORBIDDEN"]}
    assert not _expectation_satisfied(effective, bad_observation)
    bad_payload = {
        **payload,
        "results": [{**row, "observation": bad_observation}],
        "bad_cases": [{**row, "observation": bad_observation}],
        "metrics": metrics,
    }
    apply_quality_gate(bad_payload, {"case-1": entry})
    assert bad_payload["quality_gate"]["unresolved_bad_case_count"] == 1


def test_effective_contract_fails_on_forbidden_status_and_reference_tampering() -> None:
    expectation = {
        "decision": "reference_review",
        "status": "reference_review_required",
        "acceptable_ids": [],
        "forbidden_ids": ["FORBIDDEN"],
        "reference_only_ids": ["SOURCE"],
        "reason_codes": ["MANUAL_REVIEW_REQUIRED"],
        "expected_top_1": None,
        "approval_allowed": False,
        "safety_axis": "provenance",
    }
    valid = {
        "status": "reference_review_required",
        "primary_ids": [],
        "reviewable_ids": ["SOURCE"],
        "reason_codes": ["MANUAL_REVIEW_REQUIRED"],
        "trace_complete": True,
    }
    assert _expectation_satisfied(expectation, valid)
    assert not _expectation_satisfied(
        expectation,
        {**valid, "reviewable_ids": ["SOURCE", "FORBIDDEN"]},
    )
    assert not _expectation_satisfied(
        expectation,
        {**valid, "status": "recommendation_ready"},
    )
    assert not _expectation_satisfied(
        expectation,
        {**valid, "primary_ids": ["SOURCE"], "reviewable_ids": []},
    )
