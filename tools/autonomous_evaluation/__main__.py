"""CLI for the developer-only autonomous public-synthetic evaluator."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .bad_case_audit import write_inventory
from .gates import (
    DEFAULT_ADJUDICATIONS,
    apply_quality_gate,
    load_adjudications,
    quality_exit_code,
)
from .reporting import write_first_run
from .runner import generated_contract_payload, run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--first-run", action="store_true")
    parser.add_argument("--adjudications", type=Path, default=DEFAULT_ADJUDICATIONS)
    args = parser.parse_args(argv)
    payload = asyncio.run(run_evaluation(seed=args.seed))
    adjudications = load_adjudications(
        args.adjudications,
        generator_sha256=str(payload["generator"]["sha256"]),
        rows=payload["results"],
    )
    apply_quality_gate(payload, adjudications)
    if args.output:
        if args.first_run:
            write_first_run(
                args.output,
                payload,
                root=Path(__file__).resolve().parents[2],
                generated_contract=generated_contract_payload(args.seed),
            )
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            write_inventory(args.output.parent, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return quality_exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())

