"""Production-safe and explicitly isolated administration FastAPI surfaces."""

from __future__ import annotations

import inspect
import json
import os
import stat
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from uuid import uuid4

from .engine import A1FactorResolutionEngine
from .serialization import serialize_benchmark, serialize_recommendation, serialize_trace, to_jsonable

INVALID_RESOLUTION_REQUEST = "INVALID_RESOLUTION_REQUEST"
HEALTH_PROBE_FAILED = "HEALTH_PROBE_FAILED"
BENCHMARK_RUN_FAILED = "BENCHMARK_RUN_FAILED"
BENCHMARK_COMPARISON_FAILED = "BENCHMARK_COMPARISON_FAILED"
ADMIN_AUTHORIZATION_REQUIRED = "ADMIN_AUTHORIZATION_REQUIRED"
BENCHMARK_DATASET_REJECTED = "BENCHMARK_DATASET_REJECTED"
RESOLUTION_SCOPE_CONFLICT = "RESOLUTION_SCOPE_CONFLICT"
MAX_BENCHMARK_BYTES = 2_000_000
MAX_BENCHMARK_RUNS = 64
MAX_BENCHMARK_CACHE_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Identity asserted by a deployment gateway or injected authorizer."""

    actor_id: str
    tenant_id: str
    project_id: str
    permissions: tuple[str, ...] = ()


AdminAuthorizer = Callable[
    [Mapping[str, str], str],
    AuthorizationContext | None | Awaitable[AuthorizationContext | None],
]


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _run_benchmark(runner: Any, dataset_path: str) -> Any:
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


async def _probe_connectors(provider: Any) -> dict[str, Any]:
    async def safe_probe(connector: Any) -> Any:
        try:
            probe = getattr(connector, "health", connector)
            value = probe() if callable(probe) else probe
            return to_jsonable(await _maybe_await(value))
        except Exception:
            return {"status": "unhealthy", "reason_code": HEALTH_PROBE_FAILED}

    if provider is None:
        return {"status": "not_configured", "connectors": {}}
    if isinstance(provider, Mapping):
        results = {str(name): await safe_probe(connector) for name, connector in provider.items()}
        healthy = all(
            not isinstance(item, Mapping) or item.get("status") not in {"unhealthy", "error"}
            for item in results.values()
        )
        return {"status": "ok" if healthy else "degraded", "connectors": results}
    payload = await safe_probe(provider)
    return payload if isinstance(payload, dict) else {"status": "ok", "connectors": payload}


def _public_health(payload: Mapping[str, Any]) -> dict[str, str]:
    status = str(payload.get("status", "degraded"))
    return {"status": status if status in {"ok", "degraded", "not_configured"} else "degraded"}


def _default_engine() -> A1FactorResolutionEngine:
    from .external_connectors import FixtureExternalConnector, StructuredEPDEvidenceExtractor

    return A1FactorResolutionEngine(
        external_connectors=(FixtureExternalConnector(),),
        external_extractor=StructuredEPDEvidenceExtractor(),
    )


def _connector_health_for(engine: A1FactorResolutionEngine, explicit: Any) -> Any:
    if explicit is not None:
        return explicit
    connectors = getattr(getattr(engine, "graph", None), "external_connectors", ())
    return {type(item).__name__: item for item in connectors} if connectors else None


def _register_public_routes(
    app: Any,
    resolver: A1FactorResolutionEngine,
    connector_health: Any,
    *,
    resolution_authorizer: Callable[[Any, str], Awaitable[AuthorizationContext]] | None = None,
    resolution_owners: dict[str, tuple[str, str]] | None = None,
) -> None:
    from fastapi import Body, HTTPException, Request

    globals()["Request"] = Request

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/v1/resolve",
        responses={400: {"description": "Invalid structured resolution request", "content": {
            "application/json": {"example": {"detail": {
                "reason_code": INVALID_RESOLUTION_REQUEST,
                "message": "resolution request is invalid",
            }}}
        }}},
    )
    async def resolve(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        context = (
            await resolution_authorizer(request, "resolve:execute")
            if resolution_authorizer is not None
            else None
        )
        reserved_id = ""
        reserved_new = False
        if context is not None and resolution_owners is not None:
            requested_id = payload.get("request_id")
            if isinstance(requested_id, str) and requested_id.strip():
                reserved_id = requested_id.strip()
                scope = (context.tenant_id, context.project_id)
                owner = resolution_owners.get(reserved_id)
                if owner is not None and owner != scope:
                    raise HTTPException(status_code=409, detail={
                        "reason_code": RESOLUTION_SCOPE_CONFLICT,
                        "message": "resolution request id is already scoped",
                    })
                reserved_new = owner is None
                resolution_owners[reserved_id] = scope
        try:
            result = await resolver.resolve(payload)
        except (TypeError, ValueError) as exc:
            if reserved_new and resolution_owners is not None:
                resolution_owners.pop(reserved_id, None)
            raise HTTPException(status_code=400, detail={
                "reason_code": INVALID_RESOLUTION_REQUEST,
                "message": "resolution request is invalid",
            }) from exc
        except Exception:
            if reserved_new and resolution_owners is not None:
                resolution_owners.pop(reserved_id, None)
            raise
        serialized = serialize_recommendation(result)
        if context is not None and resolution_owners is not None:
            request_id = str(serialized.get("request_id", ""))
            if request_id:
                resolution_owners[request_id] = (context.tenant_id, context.project_id)
        return serialized

    @app.get("/api/v1/resolutions/{request_id}")
    async def get_resolution(request: Request, request_id: str) -> dict[str, Any]:
        if resolution_authorizer is not None:
            context = await resolution_authorizer(request, "resolution:read")
            if resolution_owners is None or resolution_owners.get(request_id) != (
                context.tenant_id,
                context.project_id,
            ):
                raise HTTPException(status_code=404, detail="resolution not found")
        result = await resolver.state(request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="resolution not found")
        return serialize_recommendation(result)

    @app.get("/api/v1/connectors/health")
    async def connectors_health() -> dict[str, str]:
        return _public_health(await _probe_connectors(connector_health))


def create_app(
    *,
    engine: A1FactorResolutionEngine | None = None,
    connector_health: Any = None,
    **legacy_admin_options: Any,
):
    """Build the production surface without benchmark, debug or full-trace routes."""

    if any(value not in (None, False, (), []) for value in legacy_admin_options.values()):
        raise ValueError("administration options require create_admin_app")
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI delivery requires fastapi and uvicorn") from exc
    resolver = engine or _default_engine()
    health = _connector_health_for(resolver, connector_health)
    app = FastAPI(title="Carbon Factor Resolver", version="1")
    app.state.engine = resolver
    _register_public_routes(app, resolver, health)
    assets = Path(__file__).with_name("web_assets")

    @app.get("/", include_in_schema=False)
    async def dashboard_index():
        return FileResponse(assets / "index.html")

    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


def create_admin_app(
    *,
    engine: A1FactorResolutionEngine | None = None,
    benchmark_runner: Any = None,
    connector_health: Any = None,
    benchmark_roots: Sequence[str | Path] = (),
    authorizer: AdminAuthorizer | None = None,
    max_benchmark_bytes: int = MAX_BENCHMARK_BYTES,
    max_benchmark_runs: int = MAX_BENCHMARK_RUNS,
    max_benchmark_cache_bytes: int = MAX_BENCHMARK_CACHE_BYTES,
):
    """Build an isolated admin/dev surface; sensitive routes require authorization."""

    try:
        from fastapi import Body, FastAPI, HTTPException, Request
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI delivery requires fastapi and uvicorn") from exc
    # Route annotations are postponed; expose the lazily imported type for
    # FastAPI/Pydantic resolution without making FastAPI a core dependency.
    globals()["Request"] = Request
    resolver = engine or _default_engine()
    health = _connector_health_for(resolver, connector_health)
    roots = tuple(Path(item).resolve() for item in benchmark_roots)
    runs: OrderedDict[tuple[str, str, str], tuple[Any, int]] = OrderedDict()
    resolution_owners: dict[str, tuple[str, str]] = {}
    app = FastAPI(title="Carbon Factor Resolver Admin", version="1")
    app.state.engine = resolver
    app.state.benchmark_runner = benchmark_runner
    app.state.benchmark_runs = runs

    async def require(request: Request, permission: str) -> AuthorizationContext:
        try:
            context = (
                None
                if authorizer is None
                else await _maybe_await(authorizer(dict(request.headers), permission))
            )
        except Exception:
            context = None
        identity_complete = bool(
            context
            and context.actor_id.strip()
            and context.tenant_id.strip()
            and context.project_id.strip()
        )
        if not identity_complete or context is None or permission not in context.permissions:
            raise HTTPException(status_code=403, detail={
                "reason_code": ADMIN_AUTHORIZATION_REQUIRED,
                "message": "administration authorization is required",
            })
        return context

    _register_public_routes(
        app,
        resolver,
        health,
        resolution_authorizer=require,
        resolution_owners=resolution_owners,
    )

    def require_resolution_owner(context: AuthorizationContext, request_id: str) -> None:
        if resolution_owners.get(request_id) != (context.tenant_id, context.project_id):
            raise HTTPException(status_code=404, detail="resolution not found")

    @app.post("/api/v1/debug/resolve")
    async def resolve_debug(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        context = await require(request, "resolve:debug")
        try:
            result = serialize_recommendation(await resolver.resolve_debug(payload))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "reason_code": INVALID_RESOLUTION_REQUEST,
                "message": "debug resolution request is invalid",
            }) from exc
        request_id = str(result.get("request_id", ""))
        if request_id:
            resolution_owners[request_id] = (context.tenant_id, context.project_id)
        return result

    @app.get("/api/v1/traces/{request_id}")
    async def get_trace(request: Request, request_id: str) -> dict[str, Any]:
        context = await require(request, "trace:read")
        require_resolution_owner(context, request_id)
        trace = await resolver.trace(request_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return serialize_trace(trace)

    @app.get("/api/v1/diagnostics/{request_id}")
    async def get_diagnostics(request: Request, request_id: str) -> dict[str, Any]:
        context = await require(request, "diagnostics:read")
        require_resolution_owner(context, request_id)
        recommendation = await resolver.state(request_id)
        trace = await resolver.trace(request_id)
        if recommendation is None or trace is None:
            raise HTTPException(status_code=404, detail="resolution diagnostics not found")
        explanation = trace.explain()
        return {
            "request_id": request_id,
            "status": to_jsonable(recommendation.status),
            "follow_up": to_jsonable(recommendation.follow_up),
            "reason_codes": to_jsonable(recommendation.reason_codes),
            "required_fields": to_jsonable(explanation.get("required_fields", ())),
            "diagnostic_candidates": to_jsonable(recommendation.diagnostic_candidates),
            "missing_gaps": to_jsonable(recommendation.missing_gaps),
            "questions": to_jsonable(recommendation.questions),
            "excluded_candidates": to_jsonable(explanation.get("excluded_candidates", ())),
            "record_qualifications": to_jsonable(explanation.get("record_qualifications", ())),
            "candidate_admissions": to_jsonable(explanation.get("candidate_admissions", ())),
            "qualification_diagnostics": to_jsonable(explanation.get("qualification_diagnostics", ())),
            "conversion_diagnostics": to_jsonable(explanation.get("conversion_diagnostics", ())),
        }

    @app.get("/api/v1/admin/connectors/health")
    async def admin_connectors_health(request: Request) -> dict[str, Any]:
        await require(request, "diagnostics:read")
        return await _probe_connectors(health)

    def checked_dataset(raw: Any) -> bytes:
        if not isinstance(raw, str) or not raw.strip():
            raise HTTPException(status_code=400, detail="path is required")
        if not roots:
            raise HTTPException(status_code=403, detail={
                "reason_code": BENCHMARK_DATASET_REJECTED,
                "message": "benchmark roots are not configured",
            })
        submitted = Path(raw).absolute()
        if submitted.suffix.casefold() != ".jsonl" or not submitted.is_file() or submitted.is_symlink():
            raise HTTPException(status_code=400, detail="benchmark path must be an existing JSONL file")
        submitted_stat = submitted.lstat()
        if not stat.S_ISREG(submitted_stat.st_mode):
            raise HTTPException(status_code=400, detail="benchmark path must be a regular JSONL file")
        path = submitted.resolve()
        if not any(path.is_relative_to(root) for root in roots):
            raise HTTPException(status_code=403, detail="benchmark path is outside configured roots")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                actual = os.fstat(stream.fileno())
                if (actual.st_dev, actual.st_ino) != (submitted_stat.st_dev, submitted_stat.st_ino):
                    raise HTTPException(status_code=400, detail="benchmark dataset changed while opening")
                payload = stream.read(max_benchmark_bytes + 1)
        except OSError as exc:
            raise HTTPException(status_code=400, detail="benchmark dataset cannot be opened") from exc
        if len(payload) > max_benchmark_bytes:
            raise HTTPException(status_code=413, detail="benchmark dataset is too large")
        return payload

    @app.post("/api/v1/benchmarks/runs", status_code=201)
    async def create_benchmark_run(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        context = await require(request, "benchmark:execute")
        if benchmark_runner is None:
            raise HTTPException(status_code=503, detail="benchmark runner is not configured")
        dataset = checked_dataset(payload.get("path") or payload.get("dataset_path"))
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as temporary:
                temporary.write(dataset)
                temporary_path = Path(temporary.name)
            result = await _run_benchmark(benchmark_runner, str(temporary_path))
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "reason_code": BENCHMARK_RUN_FAILED,
                "message": "benchmark run could not be completed",
            }) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        run_id = _run_id(result) or str(uuid4())
        response = serialize_benchmark(result)
        response["run_id"] = run_id
        result_bytes = len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if result_bytes > max_benchmark_cache_bytes:
            raise HTTPException(status_code=413, detail="benchmark result is too large")
        scope = (context.tenant_id, context.project_id)
        runs[(*scope, run_id)] = (result, result_bytes)
        while len(runs) > max_benchmark_runs or sum(item[1] for item in runs.values()) > max_benchmark_cache_bytes:
            runs.popitem(last=False)
        return response

    @app.get("/api/v1/benchmarks/runs/{run_id}")
    async def get_benchmark_run(request: Request, run_id: str) -> dict[str, Any]:
        context = await require(request, "benchmark:read")
        stored = runs.get((context.tenant_id, context.project_id, run_id))
        if stored is None:
            raise HTTPException(status_code=404, detail="benchmark run not found")
        result = stored[0]
        response = serialize_benchmark(result)
        response.setdefault("run_id", run_id)
        return response

    @app.get("/api/v1/benchmarks/compare")
    async def compare_benchmark_runs(request: Request, base: str, candidate: str) -> dict[str, Any]:
        context = await require(request, "benchmark:read")
        scope = (context.tenant_id, context.project_id)
        base_stored = runs.get((*scope, base))
        candidate_stored = runs.get((*scope, candidate))
        if base_stored is None or candidate_stored is None:
            raise HTTPException(status_code=404, detail="benchmark run not found")
        base_result, candidate_result = base_stored[0], candidate_stored[0]
        comparison = getattr(benchmark_runner, "compare", None)
        if not callable(comparison):
            from .evaluation import compare_runs

            comparison = compare_runs
        try:
            return serialize_benchmark(await _maybe_await(comparison(base_result, candidate_result)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "reason_code": BENCHMARK_COMPARISON_FAILED,
                "message": "benchmark runs could not be compared",
            }) from exc

    return app


__all__ = [
    "ADMIN_AUTHORIZATION_REQUIRED",
    "AuthorizationContext",
    "BENCHMARK_COMPARISON_FAILED",
    "BENCHMARK_DATASET_REJECTED",
    "BENCHMARK_RUN_FAILED",
    "HEALTH_PROBE_FAILED",
    "INVALID_RESOLUTION_REQUEST",
    "RESOLUTION_SCOPE_CONFLICT",
    "create_admin_app",
    "create_app",
]
