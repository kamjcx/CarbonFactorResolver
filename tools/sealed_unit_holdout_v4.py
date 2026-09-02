"""Run the final independent sealed unit holdout v4."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from tools.sealed_unit_holdout_v2 import evaluate_case, lf_sha256

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "benchmarks" / "sealed_unit_holdout_v4.jsonl"
CATALOG = ROOT / "data" / "fixtures" / "catalog" / "sealed_unit_holdout_v4_catalog.json"
FROZEN_LF_SHA256 = {
    "benchmark": "1b66f08231f15628993a26fa97b6008bc3609ec86c0009eb4937eeb8401b5a89",
    "catalog": "5c3ae062c065225346157ce5324d388c69fee84daa3565707566b95a55d44402",
}


def load_cases(path: Path = BENCHMARK) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) < 21:
        raise ValueError("sealed unit holdout v4 must contain at least 21 cases")
    ids = [str(row["case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("sealed unit holdout v4 case IDs must be unique")
    return rows


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("records"), list):
        raise ValueError("sealed unit holdout v4 catalog must contain records")
    return payload


def verify_frozen_inputs() -> dict[str, str]:
    observed = {"benchmark": lf_sha256(BENCHMARK), "catalog": lf_sha256(CATALOG)}
    if observed != FROZEN_LF_SHA256:
        raise ValueError(f"sealed unit holdout v4 hash mismatch: {observed!r}")
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
        "schema_version": "sealed-unit-holdout-result/v4",
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
