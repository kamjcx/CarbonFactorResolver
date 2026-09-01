"""Build deterministic before/after evidence for unit-dimension qualification.

This developer-only tool consumes a completed ``portfolio_validation.py`` output
directory.  It does not execute the resolver and does not modify benchmark or
catalogue inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "unit-dimension-evidence/v1"
DECISION_SCHEMA_VERSION = "unit-dimension-decision/v1"
ROOT = Path(__file__).resolve().parents[1]
CHALLENGE = ROOT / "data" / "benchmarks" / "portfolio_challenge_v1.jsonl"
CATALOGS = (
    ROOT / "data" / "fixtures" / "catalog" / "factorbench_catalog.json",
    ROOT / "data" / "fixtures" / "catalog" / "factorbench_extended_catalog.json",
    ROOT / "data" / "fixtures" / "catalog" / "portfolio_catalog_additions.json",
)
ARTIFACT_NAMES = (
    "run_manifest.json",
    "portfolio_validation.json",
    "portfolio_traces.jsonl",
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decision_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash only stable, decision-bearing fields from a case evidence row."""

    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _artifact_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_text_sha256(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _combined_catalog_sha256(paths: Sequence[Path]) -> str:
    records: list[dict[str, Any]] = []
    for path in paths:
        payload = _load_json(path)
        records.extend(_as_dict(item) for item in _as_list(payload.get("records")))
    ids = [str(record.get("record_id")) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("portfolio catalogue record IDs must be unique")
    return hashlib.sha256(_canonical_json(records)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _normalized_details(trace: Mapping[str, Any]) -> dict[str, Any]:
    entries = _as_list(trace.get("entries"))
    normalized = [
        _as_dict(entry).get("details")
        for entry in entries
        if _as_dict(entry).get("stage") == "normalize"
    ]
    return _as_dict(normalized[-1]) if normalized else {}


def _source_evidence(trace: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    local = _as_dict(trace.get("local_retrieval"))
    source_record = next(
        (
            _as_dict(item)
            for item in _as_list(local.get("records"))
            if _as_dict(item).get("source_id") == source_id
        ),
        {},
    )
    attempts = [
        {
            "strategy": str(_as_dict(item).get("strategy", "")),
            "outcome": str(_as_dict(item).get("outcome", "")),
        }
        for item in _as_list(trace.get("link_attempts"))
        if source_id in _as_list(_as_dict(item).get("candidate_source_ids"))
    ]
    qualification = next(
        (
            _as_dict(item)
            for item in _as_list(trace.get("record_qualifications"))
            if _as_dict(item).get("source_id") == source_id
        ),
        {},
    )
    admission = next(
        (
            _as_dict(item)
            for item in _as_list(trace.get("candidate_admissions"))
            if _as_dict(item).get("source_id") == source_id
        ),
        {},
    )
    exclusions = [
        _as_dict(item)
        for item in _as_list(trace.get("excluded_candidates"))
        if _as_dict(item).get("source_id") == source_id
    ]
    return {
        "source_id": source_id,
        "factor_unit": source_record.get("factor_unit"),
        "retrieval": attempts,
        "qualification": qualification or None,
        "admission": admission or None,
        "exclusions": exclusions,
    }


def _qualification_fingerprint(value: Mapping[str, Any]) -> dict[str, Any] | None:
    if not value:
        return None
    dimensions = (
        "identity",
        "factor_kind",
        "subject_type",
        "source_quality",
        "indicator",
        "declared_product",
        "boundary",
        "unit",
    )
    return {
        "statuses": {
            name: _as_dict(value.get(name)).get("status")
            for name in dimensions
        },
        "eligible": value.get("eligible"),
        "policy": value.get("policy"),
        "primary_exclusion": value.get("primary_exclusion"),
        "additional_exclusions": sorted(map(str, _as_list(value.get("additional_exclusions")))),
    }


def _source_fingerprint(value: Mapping[str, Any]) -> dict[str, Any]:
    admission = _as_dict(value.get("admission"))
    exclusions = _as_list(value.get("exclusions"))
    return {
        "source_id": value["source_id"],
        "factor_unit": value.get("factor_unit"),
        "retrieval": sorted(
            (
                {
                    "strategy": _as_dict(item).get("strategy"),
                    "outcome": _as_dict(item).get("outcome"),
                }
                for item in _as_list(value.get("retrieval"))
            ),
            key=lambda item: (str(item["strategy"]), str(item["outcome"])),
        ),
        "qualification": _qualification_fingerprint(_as_dict(value.get("qualification"))),
        "admission": (
            {
                "retrieval_strategy": admission.get("retrieval_strategy"),
                "admitted": admission.get("admitted"),
                "observation_only": admission.get("observation_only"),
                "hard_exclusions": sorted(map(str, _as_list(admission.get("hard_exclusions")))),
            }
            if admission
            else None
        ),
        "exclusion_codes": sorted(
            {
                str(reason)
                for item in exclusions
                for reason in _as_list(_as_dict(item).get("reasons"))
            }
        ),
    }


def _case_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    trace = _as_dict(row.get("trace"))
    if not trace:
        raise ValueError(f"case {row.get('case_id')} has no Full-CFR trace")
    request = _as_dict(row.get("request"))
    normalized = _normalized_details(trace)
    acceptable_ids = sorted(map(str, _as_list(row.get("acceptable_ids"))))
    expected_sources = [_source_evidence(trace, source_id) for source_id in acceptable_ids]
    required_choice = _as_dict(trace.get("required_choice"))
    funnel = _as_dict(trace.get("pipeline_funnel"))
    effective_quantity_unit = normalized.get(
        "original_quantity_unit", request.get("quantity_unit", "kg")
    )
    effective_target_unit = normalized.get(
        "target_factor_unit", request.get("target_factor_unit", "kgCO2e/kg")
    )
    decision_payload = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "case_id": str(row["case_id"]),
        "request": {
            "raw_request_fingerprint": trace.get("raw_request_fingerprint"),
            "normalized_business_fingerprint": trace.get("normalized_business_fingerprint"),
            "quantity_unit": effective_quantity_unit,
            "target_factor_unit": effective_target_unit,
        },
        "expected": {
            "decision": row.get("expected_decision"),
            "acceptable_ids": acceptable_ids,
            "forbidden_ids": sorted(map(str, _as_list(row.get("forbidden_ids")))),
        },
        "observed": {
            "status": row.get("observed_status"),
            "decision": row.get("observed_decision"),
            "returned_source_ids": list(map(str, _as_list(row.get("observed_ids")))),
            "required_choice": (
                {
                    "field": required_choice.get("field"),
                    "options": sorted(map(str, _as_list(required_choice.get("options")))),
                }
                if required_choice
                else None
            ),
        },
        "expected_sources": [_source_fingerprint(item) for item in expected_sources],
        "pipeline_funnel": {
            key: funnel.get(key)
            for key in (
                "retrieval_hits",
                "qualified_records",
                "candidate_pool",
                "ranked_candidates",
                "returned_candidates",
            )
        },
    }
    return {
        "case_id": str(row["case_id"]),
        "request": request,
        "raw_request_fingerprint": trace.get("raw_request_fingerprint"),
        "normalized_business_fingerprint": trace.get("normalized_business_fingerprint"),
        "effective_quantity_unit": effective_quantity_unit,
        "effective_target_factor_unit": effective_target_unit,
        "expected_decision": row.get("expected_decision"),
        "acceptable_ids": acceptable_ids,
        "forbidden_ids": sorted(map(str, _as_list(row.get("forbidden_ids")))),
        "observed_status": row.get("observed_status"),
        "observed_decision": row.get("observed_decision"),
        "returned_source_ids": list(map(str, _as_list(row.get("observed_ids")))),
        "required_choice": required_choice or None,
        "expected_sources": expected_sources,
        "pipeline_funnel": funnel,
        "decision_payload": decision_payload,
        "decision_fingerprint": decision_fingerprint(decision_payload),
    }


def _failed_retrieval_ids(results: Sequence[Mapping[str, Any]]) -> list[str]:
    failed: list[str] = []
    for row in results:
        if row.get("expected_decision") != "retrieve":
            continue
        acceptable = set(map(str, _as_list(row.get("acceptable_ids"))))
        returned = list(map(str, _as_list(row.get("observed_ids"))))
        if not returned or returned[0] not in acceptable:
            failed.append(str(row["case_id"]))
    return failed


def build_evidence(
    portfolio_output: Path,
    *,
    repository_root: Path = ROOT,
    before_evidence: Path | None = None,
) -> dict[str, Any]:
    """Build evidence, selecting current failures or the case set frozen in before evidence."""

    portfolio_output = portfolio_output.resolve()
    required = {name: portfolio_output / name for name in ARTIFACT_NAMES}
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"portfolio evidence artifacts are missing: {missing}")

    result = _load_json(required["portfolio_validation.json"])
    manifest = _load_json(required["run_manifest.json"])
    full = _as_dict(_as_dict(result.get("runs")).get("full_cfr"))
    results = [_as_dict(item) for item in _as_list(full.get("results"))]
    retrieval_positive_count = sum(
        row.get("expected_decision") == "retrieve" for row in results
    )
    failed_ids = _failed_retrieval_ids(results)
    if before_evidence is None:
        selection_mode = "auto_failed_retrieval"
        selected_ids = failed_ids
    else:
        before = _load_json(before_evidence)
        if before.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("before evidence uses an unsupported schema")
        selection_mode = "before_evidence"
        selected_ids = list(map(str, _as_list(before.get("selected_case_ids"))))

    by_id = {str(row.get("case_id")): row for row in results}
    unknown = [case_id for case_id in selected_ids if case_id not in by_id]
    if unknown:
        raise ValueError(f"selected case IDs are absent from Full-CFR results: {unknown}")

    challenge = repository_root / "data" / "benchmarks" / "portfolio_challenge_v1.jsonl"
    catalogs = tuple(
        repository_root / "data" / "fixtures" / "catalog" / path.name
        for path in CATALOGS
    )
    cases = [_case_evidence(by_id[case_id]) for case_id in selected_ids]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_run": {
            "commit": manifest.get("commit"),
            "git_dirty": manifest.get("git_dirty"),
        },
        "canonical_inputs": {
            "challenge": {
                "name": challenge.name,
                "sha256": _canonical_text_sha256(challenge),
            },
            "catalogs": [
                {"name": path.name, "sha256": _canonical_text_sha256(path)}
                for path in catalogs
            ],
            "combined_catalog_sha256": _combined_catalog_sha256(catalogs),
        },
        "artifact_sha256": {
            name: _artifact_sha256(path) for name, path in required.items()
        },
        "retrieval_positive_count": retrieval_positive_count,
        "observed_failed_retrieval_case_ids": failed_ids,
        "selection": {
            "mode": selection_mode,
            "before_evidence": str(before_evidence.resolve()) if before_evidence else None,
        },
        "selected_case_ids": selected_ids,
        "cases": cases,
    }


def write_evidence(evidence: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--before-evidence",
        type=Path,
        help="select the same case IDs as a prior unit-dimension-evidence/v1 artifact",
    )
    args = parser.parse_args(argv)
    evidence = build_evidence(
        args.portfolio_output,
        before_evidence=args.before_evidence,
    )
    write_evidence(evidence, args.output)
    print(json.dumps({
        "output": str(args.output),
        "selected_case_count": len(evidence["selected_case_ids"]),
        "failed_retrieval_case_count": len(evidence["observed_failed_retrieval_case_ids"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
