"""Run the frozen Unit System v1 holdout without mutating its expected answers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from a1_factor_engine import A1FactorResolutionEngine
from a1_factor_engine.adapters import HttpCatalogFactorRepository

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "benchmarks" / "unit_holdout_v1.jsonl"
CATALOG = ROOT / "data" / "fixtures" / "catalog" / "unit_holdout_catalog.json"
FROZEN_LF_SHA256 = {
    "benchmark": "b11506f56287e6a391e6959c443cfc441a186034c94c5bf3766fc8966f0bb6ff",
    "catalog": "50285f7b36b34a001385de91a6a09b90d253092873fd55984b9d2357f7297186",
}


def lf_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cases(path: Path = BENCHMARK) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) < 20:
        raise ValueError("Unit holdout must contain at least 20 cases")
    ids = [str(row["case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Unit holdout case IDs must be unique")
    return rows


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("records"), list):
        raise ValueError("Unit holdout catalog must contain records")
    return payload


def verify_frozen_inputs() -> dict[str, str]:
    observed = {"benchmark": lf_sha256(BENCHMARK), "catalog": lf_sha256(CATALOG)}
    if observed != FROZEN_LF_SHA256:
        raise ValueError(f"frozen Unit holdout hash mismatch: {observed!r}")
    return observed


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _evidence_gate(case: Mapping[str, Any], result: Any, explanation: Mapping[str, Any]) -> str:
    reason_codes = tuple(str(_value(item)) for item in result.reason_codes)
    if "UNIT_CONVERSION_EVIDENCE_REQUIRED" in reason_codes:
        return "required" if "unit_conversion_evidence" in explanation.get("required_fields", ()) else "missing_diagnostic"
    evidence = case["request"].get("unit_conversion_evidence")
    if evidence and result.candidates:
        evidence_id = str(evidence["evidence_id"])
        steps = explanation.get("transformation_steps", ())
        if any(evidence_id in item.get("parameter_ids", ()) for item in steps):
            return "passed"
        return "missing_lineage"
    return "not_applicable"


async def evaluate_case(case: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    digest = str(catalog["database"]["sha256"])
    engine = A1FactorResolutionEngine(
        local_retrieval=HttpCatalogFactorRepository(
            endpoint="fixture://unit-holdout-catalog",
            expected_sha256=digest,
            fetch_json=lambda _: catalog,
        )
    )
    request = {**case["request"], "request_id": str(case["case_id"]), "top_k": 5}
    result = await engine.resolve(request)
    explanation = result.trace.explain()
    expected = case["expected"]
    observed_ids = [candidate.source.source_id for candidate in result.candidates]
    observed_reason_codes = [str(_value(item)) for item in result.reason_codes]
    observed_follow_up = _value(result.follow_up) if result.follow_up is not None else None
    refused = not result.candidates
    evidence_gate = _evidence_gate(case, result, explanation)
    checks = {
        "status": _value(result.status) == expected["status"],
        "follow_up": observed_follow_up == expected["follow_up"],
        "recommendation": observed_ids == expected["source_ids"],
        "reason_codes": observed_reason_codes == expected["reason_codes"],
        "refusal": refused is expected["refused"],
        "evidence_gate": evidence_gate == expected["evidence_gate"],
    }
    if expected.get("factor_unit") is not None:
        checks["factor_unit"] = bool(result.candidates) and result.candidates[0].factor_unit == expected["factor_unit"]
    if expected.get("factor_value") is not None:
        checks["factor_value"] = bool(result.candidates) and math.isclose(
            result.candidates[0].factor_value, expected["factor_value"], rel_tol=1e-12, abs_tol=1e-12
        )
    if expected.get("total_emissions") is not None:
        checks["total_emissions"] = bool(result.candidates) and math.isclose(
            result.candidates[0].total_emissions_kgco2e,
            expected["total_emissions"],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    return {
        "case_id": case["case_id"],
        "coverage": case["coverage"],
        "passed": all(checks.values()),
        "checks": checks,
        "expected": expected,
        "observed": {
            "status": _value(result.status),
            "follow_up": observed_follow_up,
            "source_ids": observed_ids,
            "reason_codes": observed_reason_codes,
            "refused": refused,
            "evidence_gate": evidence_gate,
            "factor_unit": result.candidates[0].factor_unit if result.candidates else None,
            "factor_value": result.candidates[0].factor_value if result.candidates else None,
            "total_emissions": result.candidates[0].total_emissions_kgco2e if result.candidates else None,
        },
    }


async def run_holdout() -> dict[str, Any]:
    hashes = verify_frozen_inputs()
    cases = load_cases()
    catalog = load_catalog()
    results = [await evaluate_case(case, catalog) for case in cases]
    check_names = sorted({name for row in results for name in row["checks"]})
    metrics = {
        "case_count": len(results),
        "passed_count": sum(row["passed"] for row in results),
        "failed_count": sum(not row["passed"] for row in results),
        "case_pass_rate": sum(row["passed"] for row in results) / len(results),
        "check_accuracy": {
            name: sum(row["checks"].get(name, True) for row in results) / len(results)
            for name in check_names
        },
    }
    return {
        "schema_version": "unit-holdout-result/v1",
        "frozen_lf_sha256": hashes,
        "metrics": metrics,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    args = parser.parse_args()
    payload = asyncio.run(run_holdout())
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2, sort_keys=True))
    return 0 if payload["metrics"]["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
