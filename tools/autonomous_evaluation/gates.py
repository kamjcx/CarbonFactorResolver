"""Fail-closed quality gates and versioned adjudications for the evaluator."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import sha256_json
from .metrics import aggregate_metrics, bad_cases

ADJUDICATION_SCHEMA = "cfr-autonomous-adjudications/v1"
ALLOWED_DISPOSITIONS = frozenset({"accepted_limitation", "oracle_preset_error"})
DEFAULT_ADJUDICATIONS = Path("data/benchmarks/autonomous_evaluation_v3_adjudications.json")


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()


def _expectation_satisfied(
    expectation: Mapping[str, Any], observation: Mapping[str, Any]
) -> bool:
    """Evaluate an adjudicated contract without consulting runtime heuristics."""

    primary = _strings(observation.get("primary_ids"))
    reviewable = _strings(observation.get("reviewable_ids"))
    selectable = {*primary, *reviewable}
    forbidden = set(_strings(expectation.get("forbidden_ids")))
    references = set(_strings(expectation.get("reference_only_ids")))
    acceptable = set(_strings(expectation.get("acceptable_ids")))
    expected_reasons = set(_strings(expectation.get("reason_codes")))
    observed_reasons = set(_strings(observation.get("reason_codes")))
    if observation.get("status") != expectation.get("status"):
        return False
    if forbidden & selectable:
        return False
    if references and not references <= set(reviewable):
        return False
    expected_top = expectation.get("expected_top_1")
    if expected_top is not None and (not primary or primary[0] != expected_top):
        return False
    if acceptable and not (acceptable & selectable):
        return False
    if expected_reasons and not expected_reasons <= observed_reasons:
        return False
    return bool(observation.get("trace_complete", True))


def _effective_row(
    row: Mapping[str, Any], entry: Mapping[str, Any] | None
) -> dict[str, Any]:
    effective = entry.get("effective_expectation") if entry else None
    if not isinstance(effective, Mapping):
        return dict(row)
    amended = dict(row)
    amended["raw_expectation"] = row.get("expectation")
    amended["expectation"] = dict(effective)
    observation = row.get("observation", {})
    amended["passed"] = bool(
        isinstance(observation, Mapping)
        and _expectation_satisfied(amended["expectation"], observation)
    )
    return amended


def forbidden_escape_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
    expectation = row.get("expectation", {})
    observation = row.get("observation", {})
    if not isinstance(expectation, Mapping) or not isinstance(observation, Mapping):
        return ()
    forbidden = set(_strings(expectation.get("forbidden_ids")))
    selectable = {*_strings(observation.get("primary_ids")), *_strings(observation.get("reviewable_ids"))}
    return tuple(sorted(forbidden & selectable))


def load_adjudications(
    path: Path,
    *,
    generator_sha256: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load adjudications only when every identity and authority binding is valid."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ADJUDICATION_SCHEMA:
        raise ValueError("unsupported autonomous adjudication schema")
    if payload.get("evaluator_contract_sha256") != generator_sha256:
        raise ValueError("adjudication evaluator_contract_sha256 does not match this run")
    if not str(payload.get("version") or "").strip():
        raise ValueError("adjudication version is required")
    by_case = {str(row.get("case_id")): row for row in rows}
    accepted: dict[str, dict[str, Any]] = {}
    for raw in payload.get("entries", ()):
        entry = dict(raw)
        case_id = str(entry.get("case_id") or "")
        if not case_id or case_id in accepted or case_id not in by_case:
            raise ValueError(f"invalid or duplicate adjudication case_id: {case_id!r}")
        if entry.get("disposition") not in ALLOWED_DISPOSITIONS:
            raise ValueError(f"unsupported adjudication disposition for {case_id}")
        for field in ("case_sha256", "input_sha256", "reason", "reviewer", "authority", "effective_version"):
            if not str(entry.get(field) or "").strip():
                raise ValueError(f"adjudication {case_id} is missing {field}")
        row = by_case[case_id]
        if entry["case_sha256"] != row.get("semantic_fingerprint"):
            raise ValueError(f"adjudication case SHA mismatch for {case_id}")
        if entry["input_sha256"] != sha256_json(dict(row.get("request", {}))):
            raise ValueError(f"adjudication input SHA mismatch for {case_id}")
        previous = entry.get("previous_expectation")
        if previous is not None and previous != row.get("expectation"):
            raise ValueError(f"adjudication previous expectation mismatch for {case_id}")
        effective = entry.get("effective_expectation")
        if effective is not None:
            if not isinstance(effective, Mapping):
                raise ValueError(f"adjudication {case_id} effective_expectation must be an object")
            for field in (
                "decision",
                "status",
                "acceptable_ids",
                "forbidden_ids",
                "reference_only_ids",
                "reason_codes",
                "expected_top_1",
                "approval_allowed",
                "safety_axis",
            ):
                if field not in effective:
                    raise ValueError(
                        f"adjudication {case_id} effective_expectation is missing {field}"
                    )
            expected_decision = {
                "recommendation_ready": "direct",
                "more_input_needed": "more_input",
                "reference_review_required": "reference_review",
            }.get(str(effective["status"]), "abstain")
            if effective["decision"] != expected_decision:
                raise ValueError(f"adjudication status/decision mismatch for {case_id}")
            acceptable = set(_strings(effective["acceptable_ids"]))
            forbidden = set(_strings(effective["forbidden_ids"]))
            references = set(_strings(effective["reference_only_ids"]))
            if acceptable & forbidden or references & forbidden:
                raise ValueError(f"adjudication candidate sets overlap for {case_id}")
            expected_top = effective["expected_top_1"]
            if expected_top is not None and str(expected_top) not in acceptable:
                raise ValueError(f"adjudication Top-1 is not acceptable for {case_id}")
        accepted[case_id] = entry
    return accepted


def apply_quality_gate(
    payload: dict[str, Any],
    adjudications: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Add an enforceable gate without hiding raw failures or adjudicated cases."""

    failures = [dict(row) for row in payload.get("bad_cases", ())]
    annotated = []
    for row in failures:
        case_id = str(row.get("case_id"))
        entry = adjudications.get(case_id)
        row["adjudication"] = dict(entry) if entry else None
        annotated.append(row)
    payload["bad_cases"] = annotated
    effective_rows = [
        _effective_row(row, adjudications.get(str(row.get("case_id"))))
        for row in payload.get("results", ())
    ]
    effective_by_case = {str(row.get("case_id")): row for row in effective_rows}
    unresolved = []
    for row in annotated:
        entry = row["adjudication"]
        effective = entry.get("effective_expectation") if entry else None
        # Historical adjudications remain visible, but only a complete effective
        # expectation that the observation actually satisfies can close a current
        # gate failure.  A legacy note is evidence, not a waiver.
        if not isinstance(effective, Mapping):
            unresolved.append(row)
            continue
        if not bool(
            effective_by_case.get(str(row.get("case_id")), {}).get("passed")
        ):
            unresolved.append(row)
    raw_escaped = [row for row in payload.get("results", ()) if forbidden_escape_ids(row)]
    effective_escaped = [row for row in effective_rows if forbidden_escape_ids(row)]

    metrics = payload.setdefault("metrics", {})
    raw_gate = bool(metrics.get("hard_gates_pass"))
    effective_contract_count = sum(
        isinstance(entry.get("effective_expectation"), Mapping)
        for entry in adjudications.values()
    )
    has_effective_contract = bool(effective_contract_count)
    complete_effective_contract = bool(adjudications) and (
        effective_contract_count == len(adjudications)
    )
    effective_metrics = aggregate_metrics(
        effective_rows,
        relation_results=payload.get("relation_results", {}),
    )
    effective_checks = dict(effective_metrics.get("hard_gate_results", {}))
    # Forbidden candidates are never waivable.  Evaluate the contract that is
    # actually in force for each row; legacy adjudications retain the raw one.
    effective_checks["zero_forbidden_escape"] = not effective_escaped
    effective_checks["zero_unresolved_bad_cases"] = not unresolved
    state_attacks = payload.get("state_machine_attacks", ())
    effective_checks["all_state_machine_attacks_pass"] = bool(state_attacks) and all(
        bool(item.get("passed")) for item in state_attacks
    )
    effective_metrics["hard_gate_results"] = effective_checks
    effective_metrics["hard_gates_pass"] = all(effective_checks.values())
    payload["effective_metrics"] = effective_metrics
    payload["effective_bad_cases"] = bad_cases(effective_rows)
    payload["quality_gate"] = {
        "execution_status": "completed",
        "quality_status": "PASS" if effective_metrics["hard_gates_pass"] else "FAIL",
        "hard_gates_pass": effective_metrics["hard_gates_pass"],
        "raw_hard_gates_pass": raw_gate,
        "effective_contract_applied": has_effective_contract,
        "effective_contract_complete": complete_effective_contract,
        "effective_contract_count": effective_contract_count,
        "raw_bad_case_count": len(annotated),
        "effective_case_count": len(effective_rows),
        "effective_passed_case_count": sum(
            bool(row.get("passed")) for row in effective_rows
        ),
        "effective_bad_case_count": len(payload["effective_bad_cases"]),
        "adjudicated_bad_case_count": len(annotated) - len(unresolved),
        "unresolved_bad_case_count": len(unresolved),
        "raw_forbidden_escape_count": len(raw_escaped),
        "effective_forbidden_escape_count": len(effective_escaped),
        # Retained for report-schema compatibility. It now counts every
        # enforceable escape because adjudication cannot waive this safety gate.
        "unadjudicated_forbidden_escape_count": len(effective_escaped),
        "adjudicated_case_ids": sorted(adjudications),
    }
    payload["unresolved_bad_cases"] = unresolved
    return payload


def quality_exit_code(payload: Mapping[str, Any]) -> int:
    gate = payload.get("quality_gate", {})
    if not isinstance(gate, Mapping):
        return 2
    return 0 if gate.get("hard_gates_pass") is True else 2
