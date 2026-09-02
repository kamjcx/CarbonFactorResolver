"""Run the independent post-fix sealed unit holdout v3."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from tools.sealed_unit_holdout_v2 import evaluate_case, lf_sha256

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "benchmarks" / "sealed_unit_holdout_v3.jsonl"
CATALOG = ROOT / "data" / "fixtures" / "catalog" / "sealed_unit_holdout_v3_catalog.json"
FROZEN_LF_SHA256 = {
    "benchmark": "cb2e09d52aea3636db0733392c3e4521e5a451af56db869acc446046e9aff326",
    "catalog": "a75dd2c7a8e4627c9273c3eab2fb63043e47b0a3ec517235227280cfe3668d6c",
}


def load_cases(path: Path = BENCHMARK) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) < 24:
        raise ValueError("sealed unit holdout v3 must contain at least 24 cases")
    ids = [str(row["case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("sealed unit holdout v3 case IDs must be unique")
    return rows


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("records"), list):
        raise ValueError("sealed unit holdout v3 catalog must contain records")
    return payload


def verify_frozen_inputs() -> dict[str, str]:
    observed = {"benchmark": lf_sha256(BENCHMARK), "catalog": lf_sha256(CATALOG)}
    if observed != FROZEN_LF_SHA256:
        raise ValueError(f"sealed unit holdout v3 hash mismatch: {observed!r}")
    return observed


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
        "schema_version": "sealed-unit-holdout-result/v3",
        "frozen_lf_sha256": hashes,
        "metrics": metrics,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    parser.add_argument("--output", type=Path, help="write the complete result and traces")
    args = parser.parse_args()
    payload = asyncio.run(run_holdout())
    rendered = json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if payload["metrics"]["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
