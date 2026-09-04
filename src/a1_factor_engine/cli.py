"""Standard-library command line interface for resolution and FactorBench."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from .engine import A1FactorResolutionEngine
from .serialization import to_jsonable


def _demo_engine() -> A1FactorResolutionEngine:
    """Build the self-contained public demo engine with synthetic evidence."""

    from .external_connectors import FixtureExternalConnector, StructuredEPDEvidenceExtractor

    return A1FactorResolutionEngine(
        external_connectors=(FixtureExternalConnector(),),
        external_extractor=StructuredEPDEvidenceExtractor(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfr", description="Carbon factor resolution tools")
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve", help="resolve one material activity")
    resolve.add_argument("material_pos", nargs="?", help="material name")
    resolve.add_argument("quantity_pos", nargs="?", type=float, help="activity quantity")
    resolve.add_argument("unit_pos", nargs="?", help="activity unit")
    resolve.add_argument("process_pos", nargs="?", help="production process")
    resolve.add_argument("--material", dest="material_opt")
    resolve.add_argument("--quantity", dest="quantity_opt", type=float)
    resolve.add_argument("--unit", dest="unit_opt")
    resolve.add_argument("--process", dest="process_opt")
    resolve.add_argument("--request-id")
    resolve.add_argument("--geography")
    resolve.add_argument("--year", type=int)
    resolve.add_argument("--product-form")
    resolve.add_argument("--composition")
    resolve.add_argument("--boundary", default="cradle-to-gate")
    resolve.add_argument("--target-factor-unit", default="kgCO2e/kg")
    resolve.add_argument("--top-k", type=int, default=3)
    resolve.add_argument("--min-score", type=float, default=0.65)

    benchmark = commands.add_parser("benchmark", help="run or compare FactorBench results")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    run = benchmark_commands.add_parser("run", help="run a FactorBench JSONL dataset")
    run.add_argument("path")
    run.add_argument("--baseline", help="optional baseline run JSON")
    compare = benchmark_commands.add_parser("compare", help="compare two benchmark run JSON files")
    compare.add_argument("base")
    compare.add_argument("candidate")

    serve = commands.add_parser("serve", help="serve the API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _load_json(path: str | None) -> Any:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def _benchmark_run(path: str, baseline_path: str | None, runner: Any) -> Any:
    baseline = _load_json(baseline_path)
    if runner is not None:
        if baseline is None:
            return await _maybe_await(runner.run(path))
        try:
            return await _maybe_await(runner.run(path, baseline=baseline))
        except TypeError:
            return await _maybe_await(runner.run(path))
    try:
        from .evaluation import FactorBenchRunner
    except ImportError as exc:
        raise RuntimeError("FactorBench support is not available in this build") from exc
    return await FactorBenchRunner(path).run(baseline=baseline)


async def _benchmark_compare(base_path: str, candidate_path: str, runner: Any) -> Any:
    base = _load_json(base_path)
    candidate = _load_json(candidate_path)
    if runner is not None and callable(getattr(runner, "compare", None)):
        return await _maybe_await(runner.compare(base, candidate))
    try:
        from .evaluation import compare_runs
    except ImportError as exc:
        raise RuntimeError("FactorBench comparison is not available in this build") from exc
    return await _maybe_await(compare_runs(base, candidate))


def main(
    argv: Sequence[str] | None = None,
    *,
    engine: A1FactorResolutionEngine | None = None,
    benchmark_runner: Any = None,
    stdout: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    output = stdout or sys.stdout

    if args.command == "resolve":
        material = args.material_opt or args.material_pos
        quantity = args.quantity_opt if args.quantity_opt is not None else args.quantity_pos
        unit = args.unit_opt or args.unit_pos
        process = args.process_opt or args.process_pos
        if material is None or quantity is None or unit is None:
            build_parser().error("resolve requires material, quantity and unit")
        payload = {
            "material_name": material,
            "quantity": quantity,
            "quantity_unit": unit,
            "production_process": process,
            "geography": args.geography,
            "year": args.year,
            "product_form": args.product_form,
            "composition": args.composition,
            "boundary": args.boundary,
            "target_factor_unit": args.target_factor_unit,
            "top_k": args.top_k,
            "min_score": args.min_score,
        }
        if args.request_id:
            payload["request_id"] = args.request_id
        resolver = engine or _demo_engine()
        debug_resolve = getattr(resolver, "resolve_debug", resolver.resolve)
        result = asyncio.run(debug_resolve(payload))
    elif args.command == "benchmark" and args.benchmark_command == "run":
        result = asyncio.run(_benchmark_run(args.path, args.baseline, benchmark_runner))
    elif args.command == "benchmark" and args.benchmark_command == "compare":
        result = asyncio.run(_benchmark_compare(args.base, args.candidate, benchmark_runner))
    elif args.command == "serve":
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError("serve requires uvicorn and fastapi") from exc
        from .api import create_app

        uvicorn.run(
            create_app(engine=engine or _demo_engine(), benchmark_runner=benchmark_runner),
            host=args.host,
            port=args.port,
        )
        return 0
    else:  # pragma: no cover - argparse enforces this
        raise AssertionError("unreachable command")

    json.dump(to_jsonable(result), output, ensure_ascii=False, indent=2)
    output.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
