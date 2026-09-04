"""Fail-closed quality gates and versioned adjudications for the evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import sha256_json

ADJUDICATION_SCHEMA = "cfr-autonomous-adjudications/v1"
ALLOWED_DISPOSITIONS = frozenset({"accepted_limitation", "oracle_preset_error"})
DEFAULT_ADJUDICATIONS = Path("data/benchmarks/autonomous_evaluation_v1_adjudications.json")


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()


def forbidden_escape_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
    expectation = row.get("expectation", {})
    observation = row.get("observation", {})
    if not isinstance(expectation, Mapping) or not isinstance(observation, Mapping):
        return ()
    forbidden = set(_strings(expectation.get("forbidden_ids")))
    selectable = set((*_strings(observation.get("primary_ids")), *_strings(observation.get("reviewable_ids"))))
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
    unresolved = [row for row in annotated if row["adjudication"] is None]
    escaped = [row for row in payload.get("results", ()) if forbidden_escape_ids(row)]
    unadjudicated_escaped = [row for row in escaped if str(row.get("case_id")) not in adjudications]

    metrics = payload.setdefault("metrics", {})
    raw_gate = bool(metrics.get("hard_gates_pass"))
    effective_checks = dict(metrics.get("hard_gate_results", {}))
    effective_checks["zero_forbidden_escape"] = not unadjudicated_escaped
    effective_checks["zero_unresolved_bad_cases"] = not unresolved
    state_attacks = payload.get("state_machine_attacks", ())
    effective_checks["all_state_machine_attacks_pass"] = bool(state_attacks) and all(
        bool(item.get("passed")) for item in state_attacks
    )
    metrics["raw_hard_gates_pass"] = raw_gate
    metrics["hard_gate_results"] = effective_checks
    metrics["hard_gates_pass"] = all(effective_checks.values())
    payload["quality_gate"] = {
        "execution_status": "completed",
        "quality_status": "PASS" if metrics["hard_gates_pass"] else "FAIL",
        "hard_gates_pass": metrics["hard_gates_pass"],
        "raw_bad_case_count": len(annotated),
        "adjudicated_bad_case_count": len(annotated) - len(unresolved),
        "unresolved_bad_case_count": len(unresolved),
        "raw_forbidden_escape_count": len(escaped),
        "unadjudicated_forbidden_escape_count": len(unadjudicated_escaped),
        "adjudicated_case_ids": sorted(adjudications),
    }
    payload["unresolved_bad_cases"] = unresolved
    return payload


def quality_exit_code(payload: Mapping[str, Any]) -> int:
    gate = payload.get("quality_gate", {})
    if not isinstance(gate, Mapping):
        return 2
    return 0 if gate.get("hard_gates_pass") is True else 2
