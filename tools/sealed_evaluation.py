"""Run an immutable sealed JSON/API evaluation against a public-synthetic catalogue."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from httpx import ASGITransport, AsyncClient

from a1_factor_engine import A1FactorResolutionEngine
from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.api import create_app


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"sealed case line {line_number} must be an object")
        required = {
            "case_id",
            "category",
            "request",
            "expected_http_status",
            "expected_status",
            "acceptable_source_ids",
            "forbidden_source_ids",
            "expected_reason_codes",
            "safety_dimension",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"sealed case line {line_number} lacks: {', '.join(missing)}")
        if not isinstance(value["request"], (dict, list, str, int, float, bool, type(None))):
            raise ValueError(f"sealed case line {line_number} has unsupported JSON body")
        for field in ("acceptable_source_ids", "forbidden_source_ids", "expected_reason_codes"):
            if not isinstance(value[field], list) or not all(
                isinstance(item, str) for item in value[field]
            ):
                raise ValueError(f"sealed case line {line_number} field {field} must be strings")
        cases.append(value)
    ids = [str(case["case_id"]) for case in cases]
    if not cases:
        raise ValueError("sealed evaluation requires at least one case")
    if len(ids) != len(set(ids)):
        raise ValueError("sealed case_id values must be unique")
    return tuple(cases)


def load_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("sealed catalogue must be an object with records")
    ids = [str(record.get("record_id", "")) for record in payload["records"]]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("sealed catalogue record_id values must be non-empty and unique")
    return payload


def _git_sha(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _decision(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [*payload.get("candidates", ()), *payload.get("reviewable_candidates", ())]
    return {
        "http_status": payload.get("_http_status"),
        "status": payload.get("status"),
        "follow_up": payload.get("follow_up"),
        "reason_codes": payload.get("reason_codes", []),
        "source_ids": [item.get("source", {}).get("source_id") for item in candidates],
    }


async def _post_once(
    case: Mapping[str, Any], catalog: Mapping[str, Any], replay_suffix: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    database = catalog.get("database", {})
    repository = HttpCatalogFactorRepository(
        endpoint="fixture://sealed-public-catalog",
        expected_sha256=str(database.get("sha256")),
        fetch_json=lambda _endpoint: catalog,
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    app = create_app(engine=engine)
    body = case["request"]
    if isinstance(body, Mapping):
        body = dict(body)
        body["request_id"] = f"sealed:{case['case_id']}:{replay_suffix}"
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://sealed.test") as client:
        response = await client.post("/api/v1/resolve", json=body)
        trace_payload = None
        if response.status_code == 200 and isinstance(body, Mapping):
            trace_response = await client.get(f"/api/v1/traces/{body['request_id']}")
            if trace_response.status_code == 200:
                trace_payload = trace_response.json()
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_body": response.text}
    if not isinstance(payload, dict):
        payload = {"json_body": payload}
    payload["_http_status"] = response.status_code
    return payload, trace_payload


def _retrieved_source_ids(trace: Mapping[str, Any] | None) -> tuple[str, ...]:
    if trace is None:
        return ()
    for entry in trace.get("entries", ()):
        if entry.get("stage") == "local_retrieval":
            return tuple(
                str(record.get("source_id"))
                for record in entry.get("details", {}).get("records", ())
                if record.get("source_id")
            )
    return ()


async def evaluate_case(case: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    first, trace = await _post_once(case, catalog, "first")
    replay, _ = await _post_once(case, catalog, "replay")
    decision = _decision(first)
    replay_decision = _decision(replay)
    acceptable = set(case["acceptable_source_ids"])
    forbidden = set(case["forbidden_source_ids"])
    observed_ids = tuple(item for item in decision["source_ids"] if item)
    retrieved_ids = _retrieved_source_ids(trace)
    expected_http = int(case["expected_http_status"])
    expected_status = case["expected_status"]
    expected_reasons = tuple(case["expected_reason_codes"])
    answerable = bool(acceptable)
    checks = {
        "http_status": first["_http_status"] == expected_http,
        "terminal_status": decision["status"] == expected_status,
        "reason_codes": tuple(decision["reason_codes"]) == expected_reasons,
        "top_1": (not answerable) or bool(observed_ids and observed_ids[0] in acceptable),
        "retrieval_recall": (not answerable) or bool(acceptable.intersection(retrieved_ids)),
        "abstention": answerable or not observed_ids,
        "forbidden_escape": not forbidden.intersection(observed_ids),
        "deterministic_replay": decision == replay_decision,
        "trace_present": first["_http_status"] != 200 or trace is not None,
    }
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "safety_dimension": case["safety_dimension"],
        "answerable": answerable,
        "passed": all(checks.values()),
        "checks": checks,
        "expected": {
            "http_status": expected_http,
            "status": expected_status,
            "acceptable_source_ids": sorted(acceptable),
            "forbidden_source_ids": sorted(forbidden),
            "reason_codes": list(expected_reasons),
        },
        "observed": {**decision, "retrieved_source_ids": list(retrieved_ids)},
        "trace": trace,
    }


def aggregate(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    answerable = [item for item in results if item["answerable"]]
    abstentions = [item for item in results if not item["answerable"]]

    def rate(items: Sequence[Mapping[str, Any]], check: str) -> float:
        return sum(bool(item["checks"][check]) for item in items) / len(items) if items else 0.0

    violations = {name: 0 for name in ("boundary", "subject", "unit")}
    for item in results:
        dimension = item["safety_dimension"]
        if dimension in violations and not item["checks"]["forbidden_escape"]:
            violations[dimension] += 1
    return {
        "case_count": len(results),
        "answerable_case_count": len(answerable),
        "abstention_case_count": len(abstentions),
        "passed_count": sum(bool(item["passed"]) for item in results),
        "case_contract_pass_rate": (
            sum(bool(item["passed"]) for item in results) / len(results) if results else 0.0
        ),
        "answerable_top_1": rate(answerable, "top_1"),
        "retrieval_recall_before_gate": rate(answerable, "retrieval_recall"),
        "abstention_correctness": rate(abstentions, "abstention"),
        "boundary_violation_count": violations["boundary"],
        "subject_violation_count": violations["subject"],
        "unit_dimension_violation_count": violations["unit"],
        "forbidden_candidate_escape_count": sum(
            not item["checks"]["forbidden_escape"] for item in results
        ),
        "deterministic_replay": rate(results, "deterministic_replay"),
        "unhandled_http_500_count": sum(item["observed"]["http_status"] >= 500 for item in results),
    }


def release_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "case_contract": metrics["case_contract_pass_rate"] == 1.0,
        "answerable_top_1": metrics["answerable_top_1"] >= 0.90,
        "retrieval_recall_before_gate": metrics["retrieval_recall_before_gate"] >= 0.95,
        "abstention_correctness": metrics["abstention_correctness"] >= 0.90,
        "boundary_violation": metrics["boundary_violation_count"] == 0,
        "subject_violation": metrics["subject_violation_count"] == 0,
        "unit_dimension_violation": metrics["unit_dimension_violation_count"] == 0,
        "forbidden_candidate_escape": metrics["forbidden_candidate_escape_count"] == 0,
        "deterministic_replay": metrics["deterministic_replay"] == 1.0,
        "unhandled_http_500": metrics["unhandled_http_500_count"] == 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


async def run_sealed(cases_path: Path, catalog_path: Path) -> dict[str, Any]:
    cases = load_cases(cases_path)
    catalog = load_catalog(catalog_path)
    results = [await evaluate_case(case, catalog) for case in cases]
    metrics = aggregate(results)
    return {
        "schema_version": "cfr-sealed-evaluation/v2",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(cases_path.resolve().parents[2]),
        "cases_sha256": sha256_file(cases_path),
        "catalog_sha256": sha256_file(catalog_path),
        "metrics": metrics,
        "release_gate": release_gate(metrics),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = asyncio.run(run_sealed(args.cases, args.catalog))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], sort_keys=True))
    return 0 if payload["release_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
