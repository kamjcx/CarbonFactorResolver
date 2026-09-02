"""CLI for the developer-only autonomous public-synthetic evaluator."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .reporting import write_first_run
from .runner import generated_contract_payload, run_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--first-run", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(run_evaluation(seed=args.seed))
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
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

