from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType

import pytest

from a1_factor_engine.cli import main
from a1_factor_engine.serialization import (
    serialize_benchmark,
    serialize_recommendation,
    serialize_trace,
    to_jsonable,
)


class Example(Enum):
    VALUE = "value"


@dataclass
class DeliveryValue:
    enum: Example
    at: datetime
    frozen: object


def test_explicit_serializer_handles_domain_container_types():
    value = DeliveryValue(
        Example.VALUE,
        datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        MappingProxyType({"tuple": (Example.VALUE,)}),
    )

    assert to_jsonable(value) == {
        "enum": "value",
        "at": "2026-01-02T03:04:00+00:00",
        "frozen": {"tuple": ["value"]},
    }


def test_explicit_serializer_handles_paths_dates_sets_and_to_dict():
    class DictValue:
        def to_dict(self):
            return {"path": Path("evidence/report.pdf"), "date": date(2026, 9, 1)}

    assert to_jsonable({"items": {Example.VALUE}, "object": DictValue()}) == {
        "items": ["value"],
        "object": {"path": str(Path("evidence/report.pdf")), "date": "2026-09-01"},
    }


def test_delivery_serializers_require_object_payloads():
    assert serialize_recommendation({"status": "resolved"}) == {"status": "resolved"}
    assert serialize_benchmark({"run_id": "run-1"}) == {"run_id": "run-1"}
    assert serialize_trace({"entries": []}) == {"entries": []}

    with pytest.raises(TypeError, match="recommendation serializer"):
        serialize_recommendation([])
    with pytest.raises(TypeError, match="benchmark serializer"):
        serialize_benchmark([])
    with pytest.raises(TypeError, match="trace serializer"):
        serialize_trace([])
    with pytest.raises(TypeError, match="unsupported JSON value"):
        to_jsonable(object())


class FakeEngine:
    def __init__(self):
        self.requests = []

    async def resolve(self, payload):
        self.requests.append(payload)
        return {"request_id": payload.get("request_id", "generated"), "status": "unresolved"}


class FakeRunner:
    def __init__(self):
        self.runs = []

    async def run(self, path, **_kwargs):
        self.runs.append(path)
        return {"run_id": f"run-{len(self.runs)}", "metrics": {"accuracy": 0.75}}

    def compare(self, base, candidate):
        return {"accuracy": candidate["metrics"]["accuracy"] - base["metrics"]["accuracy"]}


def test_cli_resolve_maps_material_quantity_unit_and_process():
    output = io.StringIO()
    engine = FakeEngine()

    assert main(["resolve", "steel coil", "2", "t", "EAF"], engine=engine, stdout=output) == 11

    assert engine.requests[0]["material_name"] == "steel coil"
    assert engine.requests[0]["quantity"] == 2
    assert engine.requests[0]["quantity_unit"] == "t"
    assert engine.requests[0]["production_process"] == "EAF"
    assert json.loads(output.getvalue())["status"] == "unresolved"


def test_cli_benchmark_run_uses_injected_runner():
    output = io.StringIO()
    runner = FakeRunner()

    assert main(["benchmark", "run", "cases.jsonl"], benchmark_runner=runner, stdout=output) == 0

    assert runner.runs == ["cases.jsonl"]
    assert json.loads(output.getvalue())["run_id"] == "run-1"


def test_fastapi_endpoints_with_injected_services(tmp_path):
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    engine = FakeEngine()
    runner = FakeRunner()
    (tmp_path / "base.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "candidate.jsonl").write_text("{}\n", encoding="utf-8")
    async def allow(_headers, _permission):
        return AuthorizationContext("tester", "tenant", "project", (
            "resolve:execute", "resolution:read", "benchmark:execute", "benchmark:read",
            "diagnostics:read",
        ))
    app = create_admin_app(
        engine=engine,
        benchmark_runner=runner,
        connector_health={"catalog": lambda: {"status": "ok"}},
        benchmark_roots=(tmp_path,),
        authorizer=allow,
    )

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        resolved = client.post("/api/v1/resolve", json={"material_name": "steel", "quantity": 1})
        assert resolved.status_code == 200
        first = client.post("/api/v1/benchmarks/runs", json={"path": str(tmp_path / "base.jsonl")})
        second = client.post("/api/v1/benchmarks/runs", json={"path": str(tmp_path / "candidate.jsonl")})
        assert first.status_code == second.status_code == 201
        assert client.get("/api/v1/benchmarks/runs/run-1").status_code == 200
        compared = client.get("/api/v1/benchmarks/compare?base=run-1&candidate=run-2")
        assert compared.status_code == 200
        assert compared.json()["accuracy"] == 0
        assert client.get("/api/v1/admin/connectors/health").json()["status"] == "ok"


def test_fastapi_returns_not_found_for_unknown_resolution():
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    class MissingEngine(FakeEngine):
        async def state(self, _request_id):
            return None

        async def trace(self, _request_id):
            return None

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "tester", "tenant", "project",
            ("resolution:read", "trace:read", "diagnostics:read"),
        )
    with TestClient(create_admin_app(engine=MissingEngine(), authorizer=allow)) as client:
        assert client.get("/api/v1/resolutions/missing").status_code == 404
        assert client.get("/api/v1/traces/missing").status_code == 404
        assert client.get("/api/v1/diagnostics/missing").status_code == 404


def test_public_reason_code_contract_is_in_openapi_and_runtime_errors_are_redacted(tmp_path):
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import (
        BENCHMARK_COMPARISON_FAILED,
        BENCHMARK_RUN_FAILED,
        INVALID_RESOLUTION_REQUEST,
        AuthorizationContext,
        create_admin_app,
    )

    secret = "portfolio-secret-must-not-leak"

    class InvalidEngine(FakeEngine):
        async def resolve(self, _payload):
            raise ValueError(f"token={secret} internal://catalog.py:42")

    class InvalidRunner:
        async def run(self, _path):
            raise ValueError(f"token={secret} internal://benchmark.py:7")

        def compare(self, _base, _candidate):
            raise ValueError(f"token={secret} internal://compare.py:8")

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "tester", "tenant", "project",
            ("resolve:execute", "benchmark:execute", "benchmark:read"),
        )
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    app = create_admin_app(
        engine=InvalidEngine(), benchmark_runner=InvalidRunner(),
        benchmark_roots=(tmp_path,), authorizer=allow,
    )
    openapi = app.openapi()
    documented = openapi["paths"]["/api/v1/resolve"]["post"]["responses"]["400"]
    assert documented["content"]["application/json"]["example"]["detail"][
        "reason_code"
    ] == INVALID_RESOLUTION_REQUEST

    with TestClient(app) as client:
        resolved = client.post("/api/v1/resolve", json={"material_name": "steel"})
        benchmark = client.post("/api/v1/benchmarks/runs", json={"path": str(dataset)})

    assert resolved.json()["detail"]["reason_code"] == INVALID_RESOLUTION_REQUEST
    assert benchmark.json()["detail"]["reason_code"] == BENCHMARK_RUN_FAILED
    assert secret not in resolved.text + benchmark.text

    runner = InvalidRunner()
    runner.runs = []
    app = create_admin_app(engine=FakeEngine(), benchmark_runner=runner, authorizer=allow)
    app.state.benchmark_runs.update({
        ("tenant", "project", "base"): ({}, 2),
        ("tenant", "project", "candidate"): ({}, 2),
    })
    with TestClient(app) as client:
        compared = client.get("/api/v1/benchmarks/compare?base=base&candidate=candidate")
    assert compared.json()["detail"]["reason_code"] == BENCHMARK_COMPARISON_FAILED
    assert secret not in compared.text
