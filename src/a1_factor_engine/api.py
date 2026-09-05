"""Production-safe and explicitly isolated administration FastAPI surfaces."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import stat
import tempfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .engine import A1FactorResolutionEngine
from .integrity import (
    PersistenceIntegrityError,
    ReviewStateConflictError,
    StaleReviewRevisionError,
)
from .models import ResolutionRequest, resolution_request_fingerprint
from .operability import (
    API_CONTRACT_VERSION,
    API_VERSION_HEADER,
    CORRELATION_ID_HEADER,
    INTERNAL_SERVER_ERROR,
    REQUEST_ID_HEADER,
    REQUEST_VALIDATION_FAILED,
    RESOURCE_NOT_FOUND,
    SERVICE_NOT_READY,
    UNSUPPORTED_MEDIA_TYPE,
    error_detail,
)
from .operability import (
    request_id as safe_request_id,
)
from .serialization import serialize_benchmark, serialize_recommendation, serialize_trace, to_jsonable

INVALID_RESOLUTION_REQUEST = "INVALID_RESOLUTION_REQUEST"
HEALTH_PROBE_FAILED = "HEALTH_PROBE_FAILED"
BENCHMARK_RUN_FAILED = "BENCHMARK_RUN_FAILED"
BENCHMARK_COMPARISON_FAILED = "BENCHMARK_COMPARISON_FAILED"
ADMIN_AUTHORIZATION_REQUIRED = "ADMIN_AUTHORIZATION_REQUIRED"
BENCHMARK_DATASET_REJECTED = "BENCHMARK_DATASET_REJECTED"
RESOLUTION_SCOPE_CONFLICT = "RESOLUTION_SCOPE_CONFLICT"
RESOLUTION_PAYLOAD_CONFLICT = "RESOLUTION_PAYLOAD_CONFLICT"
REVIEW_STATE_CONFLICT = "REVIEW_STATE_CONFLICT"
REVIEW_INTEGRITY_CONFLICT = "REVIEW_INTEGRITY_CONFLICT"
STALE_REVIEW_REVISION = "STALE_REVIEW_REVISION"
MAX_BENCHMARK_BYTES = 2_000_000
MAX_BENCHMARK_RUNS = 64
MAX_BENCHMARK_CACHE_BYTES = 8_000_000
LOGGER = logging.getLogger("a1_factor_engine.api")


def _error_payload(correlation_id: str, reason: str, message: str) -> dict[str, Any]:
    detail = error_detail(reason, message)
    return {
        "api_version": API_CONTRACT_VERSION,
        "request_id": correlation_id,
        "correlation_id": correlation_id,
        "error": detail,
        # API v1 compatibility alias.
        "detail": detail,
    }


def _documented_error(
    description: str,
    reason: str,
    message: str,
    *,
    model: Any = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "description": description,
        "content": {"application/json": {"example": {
            **_error_payload("018f-example-correlation-id", reason, message),
            "request_id": "018f-example-correlation-id",
        }}},
        "headers": {
            API_VERSION_HEADER: {"schema": {"type": "string"}},
            REQUEST_ID_HEADER: {"schema": {"type": "string"}},
            CORRELATION_ID_HEADER: {"schema": {"type": "string"}},
        },
    }
    if model is not None:
        response["model"] = model
    return response


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


def _unconfigured_engine() -> A1FactorResolutionEngine:
    """Return an empty production engine; demo fixtures require explicit opt-in."""

    return A1FactorResolutionEngine()


def _engine_is_configured(engine: Any, *, explicitly_supplied: bool) -> bool:
    if not explicitly_supplied:
        return False
    if not isinstance(engine, A1FactorResolutionEngine):
        return True
    from .adapters import NullFactorRepository

    graph = engine.graph
    return not isinstance(graph.local_retrieval, NullFactorRepository) or bool(graph.external_connectors)


def _install_http_contract(app: Any, *, admin_review_routes: bool = False) -> None:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    globals()["Request"] = Request

    def envelope(request: Request, status_code: int, reason: str, message: str) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", safe_request_id())
        return JSONResponse(
            status_code=status_code,
            content=_error_payload(correlation_id, reason, message),
        )

    @app.middleware("http")
    async def correlation_contract(request: Request, call_next: Callable[..., Any]):
        supplied = request.headers.get("x-request-id") or request.headers.get(CORRELATION_ID_HEADER)
        request.state.correlation_id = safe_request_id(supplied)
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        review_json_route = (
            admin_review_routes
            and request.url.path.startswith("/api/v1/resolutions/")
            and request.url.path.rsplit("/", 1)[-1] in {"decisions", "locks"}
        )
        if (
            request.method == "POST"
            and (
                request.url.path in {"/api/v1/resolve", "/api/v1/debug/resolve"}
                or review_json_route
            )
            and media_type != "application/json"
            and not media_type.endswith("+json")
        ):
            response = envelope(
                request, 415, UNSUPPORTED_MEDIA_TYPE, "application/json is required"
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                LOGGER.error(
                    "unhandled API failure",
                    extra={"correlation_id": request.state.correlation_id},
                )
                response = envelope(
                    request, 500, INTERNAL_SERVER_ERROR, "internal server error"
                )
        response.headers[API_VERSION_HEADER] = API_CONTRACT_VERSION
        response.headers[REQUEST_ID_HEADER] = request.state.correlation_id
        response.headers[CORRELATION_ID_HEADER] = request.state.correlation_id
        LOGGER.info(
            "http request completed",
            extra={"correlation_id": request.state.correlation_id, "status_code": response.status_code},
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        return envelope(request, 422, REQUEST_VALIDATION_FAILED, "request validation failed")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, Mapping) and exc.detail.get("reason_code"):
            return envelope(
                request,
                exc.status_code,
                str(exc.detail["reason_code"]),
                str(exc.detail.get("message", "request could not be completed")),
            )
        reason = RESOURCE_NOT_FOUND if exc.status_code == 404 else REQUEST_VALIDATION_FAILED
        message = "resource not found" if exc.status_code == 404 else "request could not be completed"
        return envelope(request, exc.status_code, reason, message)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _exc: Exception):
        LOGGER.error(
            "unhandled API failure",
            extra={"correlation_id": request.state.correlation_id},
        )
        return envelope(request, 500, INTERNAL_SERVER_ERROR, "internal server error")


async def _readiness(
    *,
    engine_configured: bool,
    required: Mapping[str, Any],
    optional: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    async def available(probe: Any) -> bool:
        try:
            value = probe() if callable(probe) else probe
            value = await _maybe_await(value)
            if isinstance(value, Mapping):
                has_status = "status" in value
                has_available = "available" in value
                if not has_status and not has_available:
                    return False
                status_ok = (
                    isinstance(value.get("status"), str)
                    and value["status"].casefold() in {"ok", "ready", "available"}
                ) if has_status else True
                available_ok = value.get("available") is True if has_available else True
                return status_ok and available_ok
            return bool(value)
        except Exception:
            return False

    required_results = {"engine": engine_configured}
    required_results.update({name: await available(probe) for name, probe in required.items()})
    optional_results = {name: await available(probe) for name, probe in optional.items()}
    failed_required = sum(not item for item in required_results.values())
    failed_optional = sum(not item for item in optional_results.values())
    if failed_required:
        return 503, {
            "status": "not_ready",
            "detail": error_detail(SERVICE_NOT_READY, "required dependency is unavailable"),
            "required_total": len(required_results),
            "required_unavailable": failed_required,
            "optional_unavailable": failed_optional,
        }
    return 200, {
        "status": "degraded" if failed_optional else "ready",
        "required_total": len(required_results),
        "required_unavailable": 0,
        "optional_unavailable": failed_optional,
    }


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
    resolution_fingerprints: dict[tuple[str, str, str], str] | None = None,
    resolution_locks: dict[tuple[str, str, str], asyncio.Lock] | None = None,
    engine_configured: bool = True,
    required_readiness: Mapping[str, Any] | None = None,
    optional_readiness: Mapping[str, Any] | None = None,
) -> None:
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse

    from .api_contracts import (
        PublicErrorEnvelopeDTO,
        PublicReadinessErrorEnvelopeDTO,
        PublicRecommendationDTO,
        ResolutionRequestDTO,
        public_recommendation_dto,
    )

    globals()["Request"] = Request
    globals()["ResolutionRequestDTO"] = ResolutionRequestDTO
    globals()["PublicRecommendationDTO"] = PublicRecommendationDTO

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/readyz",
        responses={503: _documented_error(
            "Required dependency unavailable",
            SERVICE_NOT_READY,
            "required dependency is unavailable",
            model=PublicReadinessErrorEnvelopeDTO,
        )},
    )
    async def readyz(request: Request):
        status_code, payload = await _readiness(
            engine_configured=engine_configured,
            required=required_readiness or {},
            optional=optional_readiness or {},
        )
        if status_code != 200:
            detail = payload.get("detail", {})
            reason = (
                str(detail.get("reason_code", SERVICE_NOT_READY))
                if isinstance(detail, Mapping) else SERVICE_NOT_READY
            )
            message = (
                str(detail.get("message", "required dependency is unavailable"))
                if isinstance(detail, Mapping) else "required dependency is unavailable"
            )
            payload = {
                **_error_payload(request.state.correlation_id, reason, message),
                "required_total": payload.get("required_total", 0),
                "required_unavailable": payload.get("required_unavailable", 0),
                "optional_unavailable": payload.get("optional_unavailable", 0),
            }
        return JSONResponse(status_code=status_code, content=payload)

    @app.post(
        "/api/v1/resolve",
        response_model=PublicRecommendationDTO,
        response_model_exclude_none=True,
        openapi_extra={"x-cfr-reason-codes": [
            INVALID_RESOLUTION_REQUEST,
            RESOLUTION_SCOPE_CONFLICT,
            RESOLUTION_PAYLOAD_CONFLICT,
            UNSUPPORTED_MEDIA_TYPE,
            REQUEST_VALIDATION_FAILED,
            INTERNAL_SERVER_ERROR,
        ]},
        responses={
            400: _documented_error(
                "Invalid structured resolution request",
                INVALID_RESOLUTION_REQUEST,
                "resolution request is invalid",
                model=PublicErrorEnvelopeDTO,
            ),
            409: _documented_error(
                "Request ID scope conflict",
                RESOLUTION_SCOPE_CONFLICT,
                "resolution request id is already scoped",
                model=PublicErrorEnvelopeDTO,
            ),
            415: _documented_error(
                "JSON media type required", UNSUPPORTED_MEDIA_TYPE, "application/json is required",
                model=PublicErrorEnvelopeDTO,
            ),
            422: _documented_error(
                "JSON request validation failed",
                REQUEST_VALIDATION_FAILED,
                "request validation failed",
                model=PublicErrorEnvelopeDTO,
            ),
            500: _documented_error(
                "Stable internal failure", INTERNAL_SERVER_ERROR, "internal server error",
                model=PublicErrorEnvelopeDTO,
            ),
        },
    )
    async def resolve(
        request: Request,
        payload: ResolutionRequestDTO,
    ) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise HTTPException(
                status_code=415,
                detail=error_detail(UNSUPPORTED_MEDIA_TYPE, "application/json is required"),
            )
        payload_mapping = payload.to_domain_mapping()
        payload_mapping["request_id"] = safe_request_id(
            payload_mapping.get("request_id") or request.headers.get(REQUEST_ID_HEADER)
            or request.headers.get(CORRELATION_ID_HEADER)
        )
        request.state.correlation_id = payload_mapping["request_id"]
        context = (
            await resolution_authorizer(request, "resolve:execute")
            if resolution_authorizer is not None
            else None
        )
        try:
            parsed_request = ResolutionRequest.from_mapping(payload_mapping)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "reason_code": INVALID_RESOLUTION_REQUEST,
                "message": "resolution request is invalid",
            }) from exc
        fingerprint = resolution_request_fingerprint(parsed_request)
        scope = (
            (context.tenant_id, context.project_id)
            if context is not None else ("__public__", "__public__")
        )
        key = (*scope, parsed_request.request_id)
        fingerprints = resolution_fingerprints if resolution_fingerprints is not None else {}
        locks = resolution_locks if resolution_locks is not None else {}
        lock = locks.setdefault(key, asyncio.Lock())
        async with lock:
            reserved_new = False
            if context is not None and resolution_owners is not None:
                owner = resolution_owners.get(parsed_request.request_id)
                if owner is not None and owner != scope:
                    raise HTTPException(status_code=409, detail={
                        "reason_code": RESOLUTION_SCOPE_CONFLICT,
                        "message": "resolution request id is already scoped",
                    })
                reserved_new = owner is None
                resolution_owners[parsed_request.request_id] = scope
            known_fingerprint = fingerprints.get(key)
            if known_fingerprint is not None and known_fingerprint != fingerprint:
                if reserved_new and resolution_owners is not None:
                    resolution_owners.pop(parsed_request.request_id, None)
                raise HTTPException(status_code=409, detail={
                    "reason_code": RESOLUTION_PAYLOAD_CONFLICT,
                    "message": "resolution request id is bound to different input",
                })
            state_reader = getattr(resolver, "state", None)
            existing = (
                await _maybe_await(state_reader(parsed_request.request_id))
                if callable(state_reader) else None
            )
            if existing is not None:
                if known_fingerprint is None:
                    if reserved_new and resolution_owners is not None:
                        resolution_owners.pop(parsed_request.request_id, None)
                    raise HTTPException(status_code=409, detail={
                        "reason_code": RESOLUTION_PAYLOAD_CONFLICT,
                        "message": "stored resolution lacks an idempotency binding",
                    })
                return public_recommendation_dto(
                    existing,
                    request_id=parsed_request.request_id,
                ).model_dump(mode="json", exclude_none=True)
            fingerprints[key] = fingerprint
            try:
                result = await resolver.resolve(payload_mapping)
            except (TypeError, ValueError) as exc:
                fingerprints.pop(key, None)
                if reserved_new and resolution_owners is not None:
                    resolution_owners.pop(parsed_request.request_id, None)
                raise HTTPException(status_code=400, detail={
                    "reason_code": INVALID_RESOLUTION_REQUEST,
                    "message": "resolution request is invalid",
                }) from exc
            except Exception:
                fingerprints.pop(key, None)
                if reserved_new and resolution_owners is not None:
                    resolution_owners.pop(parsed_request.request_id, None)
                raise
            serialized = public_recommendation_dto(
                result,
                request_id=parsed_request.request_id,
            ).model_dump(mode="json", exclude_none=True)
            serialized["request_id"] = safe_request_id(
                serialized.get("request_id") or parsed_request.request_id
            )
            request.state.correlation_id = serialized["request_id"]
            return serialized

    @app.get(
        "/api/v1/resolutions/{request_id}",
        response_model=PublicRecommendationDTO,
        response_model_exclude_none=True,
    )
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
        return public_recommendation_dto(result, request_id=request_id).model_dump(
            mode="json", exclude_none=True
        )

    @app.get("/api/v1/connectors/health")
    async def connectors_health() -> dict[str, str]:
        return _public_health(await _probe_connectors(connector_health))


def create_app(
    *,
    engine: A1FactorResolutionEngine | None = None,
    connector_health: Any = None,
    required_readiness: Mapping[str, Any] | None = None,
    optional_readiness: Mapping[str, Any] | None = None,
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
    resolver = engine or _unconfigured_engine()
    engine_configured = _engine_is_configured(resolver, explicitly_supplied=engine is not None)
    health = _connector_health_for(resolver, connector_health)
    app = FastAPI(title="Carbon Factor Resolver", version=API_CONTRACT_VERSION)
    app.state.engine = resolver
    resolution_fingerprints: dict[tuple[str, str, str], str] = {}
    resolution_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
    app.state.resolution_fingerprints = resolution_fingerprints
    _install_http_contract(app)
    optional = dict(optional_readiness or {})
    if connector_health is not None:
        optional.setdefault("connectors", lambda: _probe_connectors(health))
    _register_public_routes(
        app,
        resolver,
        health,
        resolution_fingerprints=resolution_fingerprints,
        resolution_locks=resolution_locks,
        engine_configured=engine_configured,
        required_readiness=required_readiness,
        optional_readiness=optional,
    )
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
    from .api_contracts import (
        PublicErrorEnvelopeDTO,
        ReviewDecisionRequestDTO,
        ReviewDecisionResponseDTO,
        ReviewLockRequestDTO,
        ReviewLockResponseDTO,
        review_decision_dto,
        review_lock_dto,
    )

    globals()["ReviewDecisionRequestDTO"] = ReviewDecisionRequestDTO
    globals()["ReviewDecisionResponseDTO"] = ReviewDecisionResponseDTO
    globals()["ReviewLockRequestDTO"] = ReviewLockRequestDTO
    globals()["ReviewLockResponseDTO"] = ReviewLockResponseDTO
    resolver = engine or _unconfigured_engine()
    engine_configured = _engine_is_configured(resolver, explicitly_supplied=engine is not None)
    health = _connector_health_for(resolver, connector_health)
    roots = tuple(Path(item).resolve() for item in benchmark_roots)
    runs: OrderedDict[tuple[str, str, str], tuple[Any, int]] = OrderedDict()
    resolution_owners: dict[str, tuple[str, str]] = {}
    resolution_fingerprints: dict[tuple[str, str, str], str] = {}
    resolution_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
    app = FastAPI(title="Carbon Factor Resolver Admin", version=API_CONTRACT_VERSION)
    app.state.engine = resolver
    app.state.benchmark_runner = benchmark_runner
    app.state.benchmark_runs = runs
    app.state.resolution_fingerprints = resolution_fingerprints
    _install_http_contract(app, admin_review_routes=True)

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
        resolution_fingerprints=resolution_fingerprints,
        resolution_locks=resolution_locks,
        engine_configured=engine_configured,
        optional_readiness={"connectors": lambda: _probe_connectors(health)} if health else {},
    )

    def require_resolution_owner(context: AuthorizationContext, request_id: str) -> None:
        if resolution_owners.get(request_id) != (context.tenant_id, context.project_id):
            raise HTTPException(status_code=404, detail="resolution not found")

    review_conflict_responses: dict[int | str, dict[str, Any]] = {
        409: _documented_error(
            "Review state or revision conflict",
            REVIEW_STATE_CONFLICT,
            "review operation conflicts with committed state",
            model=PublicErrorEnvelopeDTO,
        ),
        415: _documented_error(
            "JSON media type required",
            UNSUPPORTED_MEDIA_TYPE,
            "application/json is required",
            model=PublicErrorEnvelopeDTO,
        ),
        422: _documented_error(
            "JSON request validation failed",
            REQUEST_VALIDATION_FAILED,
            "request validation failed",
            model=PublicErrorEnvelopeDTO,
        ),
    }

    def raise_review_error(exc: Exception) -> None:
        if isinstance(exc, StaleReviewRevisionError):
            reason = STALE_REVIEW_REVISION
            message = "review trace revision is stale"
        elif isinstance(exc, PersistenceIntegrityError):
            reason = REVIEW_INTEGRITY_CONFLICT
            message = "review integrity validation failed"
        else:
            reason = REVIEW_STATE_CONFLICT
            message = "review operation conflicts with committed state"
        raise HTTPException(
            status_code=409,
            detail={"reason_code": reason, "message": message},
        ) from exc

    @app.post(
        "/api/v1/resolutions/{request_id}/decisions",
        response_model=ReviewDecisionResponseDTO,
        responses=review_conflict_responses,
        openapi_extra={"x-cfr-reason-codes": [
            REVIEW_STATE_CONFLICT,
            REVIEW_INTEGRITY_CONFLICT,
            STALE_REVIEW_REVISION,
            ADMIN_AUTHORIZATION_REQUIRED,
        ]},
    )
    async def create_review_decision(
        request: Request,
        request_id: str,
        payload: ReviewDecisionRequestDTO,
    ) -> dict[str, Any]:
        context = await require(request, "review:write")
        require_resolution_owner(context, request_id)
        try:
            if payload.decision == "approve":
                decision = await resolver.approve(
                    request_id,
                    payload.candidate_id,
                    context.actor_id,
                    payload.note,
                    payload.mode,
                    expected_trace_revision=payload.expected_trace_revision,
                )
            else:
                decision = await resolver.reject(
                    request_id,
                    payload.candidate_id,
                    context.actor_id,
                    payload.note,
                    expected_trace_revision=payload.expected_trace_revision,
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review target not found") from exc
        except (PersistenceIntegrityError, ReviewStateConflictError, ValueError) as exc:
            raise_review_error(exc)
        return review_decision_dto(decision).model_dump(mode="json")

    @app.post(
        "/api/v1/resolutions/{request_id}/locks",
        response_model=ReviewLockResponseDTO,
        responses=review_conflict_responses,
        openapi_extra={"x-cfr-reason-codes": [
            REVIEW_STATE_CONFLICT,
            REVIEW_INTEGRITY_CONFLICT,
            STALE_REVIEW_REVISION,
            ADMIN_AUTHORIZATION_REQUIRED,
        ]},
    )
    async def lock_reviewed_resolution(
        request: Request,
        request_id: str,
        payload: ReviewLockRequestDTO,
    ) -> dict[str, Any]:
        context = await require(request, "review:lock")
        require_resolution_owner(context, request_id)
        try:
            locked = await resolver.lock(
                request_id,
                payload.candidate_id,
                context.actor_id,
                expected_trace_revision=payload.expected_trace_revision,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review target not found") from exc
        except (PersistenceIntegrityError, ReviewStateConflictError, ValueError) as exc:
            raise_review_error(exc)
        return review_lock_dto(locked).model_dump(mode="json")

    @app.post("/api/v1/debug/resolve")
    async def resolve_debug(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        context = await require(request, "resolve:debug")
        payload = dict(payload)
        payload["request_id"] = safe_request_id(
            payload.get("request_id") or request.headers.get("x-request-id")
            or request.headers.get(CORRELATION_ID_HEADER)
        )
        request.state.correlation_id = payload["request_id"]
        try:
            result = serialize_recommendation(await resolver.resolve_debug(payload))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "reason_code": INVALID_RESOLUTION_REQUEST,
                "message": "debug resolution request is invalid",
            }) from exc
        request_id = safe_request_id(result.get("request_id") or payload["request_id"])
        result["request_id"] = request_id
        request.state.correlation_id = request_id
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
    "RESOLUTION_PAYLOAD_CONFLICT",
    "RESOLUTION_SCOPE_CONFLICT",
    "REVIEW_INTEGRITY_CONFLICT",
    "REVIEW_STATE_CONFLICT",
    "STALE_REVIEW_REVISION",
    "create_admin_app",
    "create_app",
]
