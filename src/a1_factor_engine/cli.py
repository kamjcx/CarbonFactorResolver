"""Standard-library command line interface for resolution and FactorBench."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, TextIO

from .engine import A1FactorResolutionEngine
from .operability import CliExitCode, cli_exit_code, error_detail
from .operability import request_id as safe_request_id
from .serialization import to_jsonable

CLI_INVALID_REQUEST = "CLI_INVALID_REQUEST"
CLI_INTERNAL_FAILURE = "CLI_INTERNAL_FAILURE"


class CliUsageError(ValueError):
    pass


class ContractArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


def _demo_engine() -> A1FactorResolutionEngine:
    """Build the self-contained public demo engine with synthetic evidence."""

    from .external_connectors import FixtureExternalConnector, StructuredEPDEvidenceExtractor

    return A1FactorResolutionEngine(
        external_connectors=(FixtureExternalConnector(),),
        external_extractor=StructuredEPDEvidenceExtractor(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = ContractArgumentParser(prog="cfr", description="Carbon factor resolution tools")
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser(
        "resolve",
        help="resolve structured JSON, or use the positional material-mass shortcut",
    )
    resolve.add_argument("material_pos", nargs="?", help="material name (mass shortcut only)")
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
    resolve.add_argument("--target-factor-unit")
    resolve.add_argument("--top-k", type=int, default=3)
    resolve.add_argument(
        "--min-score", type=float, default=None,
        help="deprecated debug control; formal resolve rejects this option",
    )
    resolve.add_argument("--input-json", metavar="PATH_OR_DASH", help="structured JSON request; '-' reads stdin")
    resolve.add_argument("--demo", action="store_true", help="explicitly use public synthetic demo data")

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
    serve.add_argument("--demo", action="store_true", help="explicitly serve public synthetic demo data")
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
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    diagnostics = stderr or sys.stderr
    input_stream = stdin or sys.stdin

    def emit(value: Mapping[str, Any]) -> None:
        json.dump(to_jsonable(value), output, ensure_ascii=False, separators=(",", ":"))
        output.write("\n")

    try:
        args = build_parser().parse_args(argv)
    except CliUsageError:
        emit({"detail": error_detail(CLI_INVALID_REQUEST, "invalid command arguments")})
        diagnostics.write("cfr: invalid command arguments\n")
        return int(CliExitCode.INVALID_REQUEST)

    try:
        if args.command == "resolve":
            if args.min_score is not None:
                raise CliUsageError("--min-score is not available on formal resolve")
            positional_used = any(value is not None for value in (
                args.material_pos, args.quantity_pos, args.unit_pos, args.process_pos
            ))
            option_used = any(value is not None for value in (
                args.material_opt,
                args.quantity_opt,
                args.unit_opt,
                args.process_opt,
                args.geography,
                args.year,
                args.product_form,
                args.composition,
                args.target_factor_unit,
            ))
            if args.input_json and (positional_used or option_used):
                raise CliUsageError("--input-json cannot be combined with resolution field options")
            if positional_used and any(value is not None for value in (
                args.material_opt, args.quantity_opt, args.unit_opt, args.process_opt
            )):
                raise CliUsageError("positional resolve cannot be mixed with field options")
            if args.input_json:
                raw = input_stream.read() if args.input_json == "-" else Path(args.input_json).read_text(
                    encoding="utf-8"
                )
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise CliUsageError("resolution input must be a JSON object")
            else:
                from .units import ActivityDimension, parse_activity_unit

                material = args.material_opt or args.material_pos
                quantity = args.quantity_opt if args.quantity_opt is not None else args.quantity_pos
                unit = args.unit_opt or args.unit_pos
                process = args.process_opt or args.process_pos
                if material is None or quantity is None or unit is None:
                    raise CliUsageError("resolve requires material, quantity and unit")
                activity_unit = parse_activity_unit(unit)
                if activity_unit.dimension != ActivityDimension.MASS:
                    raise CliUsageError(
                        "positional resolve supports material mass only; use --input-json"
                    )
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
                    "target_factor_unit": args.target_factor_unit or "kgCO2e/kg",
                    "top_k": args.top_k,
                }
                if args.request_id:
                    payload["request_id"] = args.request_id
            if engine is None and not args.demo:
                raise CliUsageError("resolve requires an injected engine or explicit --demo")
            payload["request_id"] = safe_request_id(payload.get("request_id"))
            resolver = engine or _demo_engine()
            result = asyncio.run(resolver.resolve(payload))
            serialized = to_jsonable(result)
            if not isinstance(serialized, dict):
                raise TypeError("resolver result must be an object")
            emit(serialized)
            return int(cli_exit_code(serialized))
        if args.command == "benchmark" and args.benchmark_command == "run":
            result = asyncio.run(_benchmark_run(args.path, args.baseline, benchmark_runner))
        elif args.command == "benchmark" and args.benchmark_command == "compare":
            result = asyncio.run(_benchmark_compare(args.base, args.candidate, benchmark_runner))
        elif args.command == "serve":
            try:
                import uvicorn
            except ImportError as exc:
                raise RuntimeError("serve dependencies are unavailable") from exc
            from .api import create_app

            selected_engine = engine or (_demo_engine() if args.demo else None)
            uvicorn.run(create_app(engine=selected_engine), host=args.host, port=args.port)
            return int(CliExitCode.SUCCESS)
        else:  # pragma: no cover - argparse enforces this
            raise AssertionError("unreachable command")
        serialized = to_jsonable(result)
        if not isinstance(serialized, dict):
            raise TypeError("command result must be an object")
        emit(serialized)
        return int(CliExitCode.SUCCESS)
    except (CliUsageError, json.JSONDecodeError, OSError, ValueError):
        emit({"detail": error_detail(CLI_INVALID_REQUEST, "request could not be parsed or validated")})
        diagnostics.write("cfr: invalid request\n")
        return int(CliExitCode.INVALID_REQUEST)
    except Exception:
        emit({"detail": error_detail(CLI_INTERNAL_FAILURE, "internal command failure")})
        diagnostics.write("cfr: internal failure\n")
        return int(CliExitCode.INTERNAL_FAILURE)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["CLI_INTERNAL_FAILURE", "CLI_INVALID_REQUEST", "build_parser", "main"]
