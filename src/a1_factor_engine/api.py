"""Optional FastAPI delivery surface for the factor resolution engine."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .engine import A1FactorResolutionEngine
from .serialization import serialize_benchmark, serialize_recommendation, serialize_trace, to_jsonable


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _run_benchmark(runner: Any, dataset_path: str) -> Any:
    """Support an injected runner instance or a ``path -> runner`` factory."""

    if inspect.isclass(runner) or (callable(runner) and not callable(getattr(runner, "run", None))):
        return await _maybe_await(runner(dataset_path).run())
    run = getattr(runner, "run", None)
    if not callable(run):
        raise TypeError("benchmark runner must expose run(path) or be a runner factory")
    parameters = tuple(inspect.signature(run).parameters.values())
    if parameters and parameters[0].name == "baseline" and hasattr(runner, "dataset_path"):
        configured = Path(runner.dataset_path)
        if configured != Path(dataset_path):
            raise ValueError("injected benchmark runner is configured for a different dataset")
        return await _maybe_await(run())
    return await _maybe_await(run(dataset_path))


def _run_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        candidate = value.get("run_id") or value.get("id")
    else:
        candidate = getattr(value, "run_id", None) or getattr(value, "id", None)
    return str(candidate) if candidate else None


async def _connector_payload(provider: Any) -> dict[str, Any]:
    if provider is None:
        return {"status": "not_configured", "connectors": {}}
    if isinstance(provider, Mapping):
        results: dict[str, Any] = {}
        for name, connector in provider.items():
            try:
                probe = getattr(connector, "health", connector)
                value = probe() if callable(probe) else probe
                results[str(name)] = to_jsonable(await _maybe_await(value))
            except Exception as exc:  # Health must report failures without taking down the endpoint.
                results[str(name)] = {"status": "unhealthy", "error": str(exc)}
        healthy = all(
            not isinstance(item, Mapping) or item.get("status") not in {"unhealthy", "error"}
            for item in results.values()
        )
        return {"status": "ok" if healthy else "degraded", "connectors": results}
    probe = getattr(provider, "health", provider)
    payload = to_jsonable(await _maybe_await(probe()))
    return payload if isinstance(payload, dict) else {"status": "ok", "connectors": payload}


def create_app(
    *,
    engine: A1FactorResolutionEngine | None = None,
    benchmark_runner: Any = None,
    connector_health: Any = None,
    benchmark_roots: Sequence[str | Path] | None = None,
):
    """Build an application with injected domain services.

    FastAPI is imported lazily so the dependency-free engine remains usable
    without installing the HTTP extras. Benchmark results live only in this
    process; persistent benchmark storage belongs to a deployment adapter.
    """

    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("FastAPI delivery requires fastapi and uvicorn") from exc

    if engine is None:
        from .external_connectors import FixtureExternalConnector, StructuredEPDEvidenceExtractor

        engine = A1FactorResolutionEngine(
            external_connectors=(FixtureExternalConnector(),),
            external_extractor=StructuredEPDEvidenceExtractor(),
        )
    resolver = engine
    if connector_health is None:
        configured_connectors = getattr(getattr(resolver, "graph", None), "external_connectors", ())
        if configured_connectors:
            connector_health = {
                type(connector).__name__: connector for connector in configured_connectors
            }
    restrict_default_runner = benchmark_runner is None
    if benchmark_runner is None:
        try:
            from .evaluation import FactorBenchRunner

            benchmark_runner = FactorBenchRunner
        except ImportError:
            pass
    if benchmark_roots is not None:
        allowed_benchmark_roots = tuple(Path(item).resolve() for item in benchmark_roots)
    elif restrict_default_runner:
        allowed_benchmark_roots = (
            (Path(__file__).resolve().parents[2] / "data" / "benchmarks").resolve(),
            (Path(sys.prefix) / "share" / "carbon-factor-resolver" / "benchmarks").resolve(),
        )
    else:
        allowed_benchmark_roots = ()
    benchmark_runs: dict[str, Any] = {}
    app = FastAPI(title="A1 Factor Resolution", version="1")
    app.state.engine = resolver
    app.state.benchmark_runner = benchmark_runner
    app.state.benchmark_runs = benchmark_runs

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/resolve")
    async def resolve(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            result = await resolver.resolve(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return serialize_recommendation(result)

    @app.get("/api/v1/resolutions/{request_id}")
    async def get_resolution(request_id: str) -> dict[str, Any]:
        result = await resolver.state(request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="resolution not found")
        return serialize_recommendation(result)

    @app.get("/api/v1/traces/{request_id}")
    async def get_trace(request_id: str) -> dict[str, Any]:
        trace = await resolver.trace(request_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return serialize_trace(trace)

    @app.get("/api/v1/diagnostics/{request_id}")
    async def get_diagnostics(request_id: str) -> dict[str, Any]:
        recommendation = await resolver.state(request_id)
        trace = await resolver.trace(request_id)
        if recommendation is None or trace is None:
            raise HTTPException(status_code=404, detail="resolution diagnostics not found")
        explanation = trace.explain()
        return {
            "request_id": request_id,
            "status": to_jsonable(recommendation.status),
            "diagnostic_candidates": to_jsonable(recommendation.diagnostic_candidates),
            "missing_gaps": to_jsonable(recommendation.missing_gaps),
            "questions": to_jsonable(recommendation.questions),
            "excluded_candidates": to_jsonable(explanation.get("excluded_candidates", ())),
            "record_qualifications": to_jsonable(explanation.get("record_qualifications", ())),
            "candidate_admissions": to_jsonable(explanation.get("candidate_admissions", ())),
        }

    @app.post("/api/v1/benchmarks/runs", status_code=201)
    async def create_benchmark_run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if benchmark_runner is None:
            raise HTTPException(status_code=503, detail="benchmark runner is not configured")
        dataset_path = payload.get("path") or payload.get("dataset_path")
        if not isinstance(dataset_path, str) or not dataset_path.strip():
            raise HTTPException(status_code=400, detail="path is required")
        resolved_dataset = Path(dataset_path).resolve()
        if allowed_benchmark_roots and not any(
            resolved_dataset.is_relative_to(root) for root in allowed_benchmark_roots
        ):
            raise HTTPException(status_code=403, detail="benchmark path is outside configured roots")
        if resolved_dataset.suffix.casefold() != ".jsonl":
            raise HTTPException(status_code=400, detail="benchmark path must be a JSONL file")
        try:
            result = await _run_benchmark(benchmark_runner, str(resolved_dataset))
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        run_id = _run_id(result) or str(uuid4())
        benchmark_runs[run_id] = result
        response = serialize_benchmark(result)
        response.setdefault("run_id", run_id)
        return response

    @app.get("/api/v1/benchmarks/runs/{run_id}")
    async def get_benchmark_run(run_id: str) -> dict[str, Any]:
        result = benchmark_runs.get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="benchmark run not found")
        response = serialize_benchmark(result)
        response.setdefault("run_id", run_id)
        return response

    @app.get("/api/v1/benchmarks/compare")
    async def compare_benchmark_runs(
        base: str | None = None,
        candidate: str | None = None,
        baseline: str | None = None,
        base_run_id: str | None = None,
        candidate_run_id: str | None = None,
    ) -> dict[str, Any]:
        base_id = base or baseline or base_run_id
        candidate_id = candidate or candidate_run_id
        if not base_id or not candidate_id:
            raise HTTPException(status_code=400, detail="base and candidate run ids are required")
        base = benchmark_runs.get(base_id)
        candidate = benchmark_runs.get(candidate_id)
        if base is None or candidate is None:
            raise HTTPException(status_code=404, detail="benchmark run not found")
        compare = getattr(benchmark_runner, "compare", None)
        if not callable(compare):
            try:
                from .evaluation import compare_runs as compare
            except ImportError:
                compare = None
        if not callable(compare):
            raise HTTPException(status_code=503, detail="benchmark comparison is not configured")
        try:
            result = await _maybe_await(compare(base, candidate))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return serialize_benchmark(result)

    @app.get("/api/v1/connectors/health")
    async def connectors_health() -> dict[str, Any]:
        return await _connector_payload(connector_health)

    assets = Path(__file__).with_name("web_assets")

    @app.get("/", include_in_schema=False)
    async def dashboard_index():
        return FileResponse(assets / "index.html")

    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


__all__ = ["create_app"]
