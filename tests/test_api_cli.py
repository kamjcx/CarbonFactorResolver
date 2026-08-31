from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType

import pytest

from a1_factor_engine.cli import main
from a1_factor_engine.serialization import to_jsonable


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
        datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        MappingProxyType({"tuple": (Example.VALUE,)}),
    )

    assert to_jsonable(value) == {
        "enum": "value",
        "at": "2026-01-02T03:04:00+00:00",
        "frozen": {"tuple": ["value"]},
    }


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

    assert main(["resolve", "steel coil", "2", "t", "EAF"], engine=engine, stdout=output) == 0

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


def test_fastapi_endpoints_with_injected_services():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    engine = FakeEngine()
    runner = FakeRunner()
    app = create_app(
        engine=engine,
        benchmark_runner=runner,
        connector_health={"catalog": lambda: {"status": "ok"}},
    )

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        resolved = client.post("/api/v1/resolve", json={"material_name": "steel", "quantity": 1})
        assert resolved.status_code == 200
        first = client.post("/api/v1/benchmarks/runs", json={"path": "base.jsonl"})
        second = client.post("/api/v1/benchmarks/runs", json={"path": "candidate.jsonl"})
        assert first.status_code == second.status_code == 201
        assert client.get("/api/v1/benchmarks/runs/run-1").status_code == 200
        compared = client.get("/api/v1/benchmarks/compare?base=run-1&candidate=run-2")
        assert compared.status_code == 200
        assert compared.json()["accuracy"] == 0
        assert client.get("/api/v1/connectors/health").json()["status"] == "ok"
        assert client.get("/").status_code == 200


def test_fastapi_returns_not_found_for_unknown_resolution():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    class MissingEngine(FakeEngine):
        async def state(self, _request_id):
            return None

        async def trace(self, _request_id):
            return None

    with TestClient(create_app(engine=MissingEngine())) as client:
        assert client.get("/api/v1/resolutions/missing").status_code == 404
        assert client.get("/api/v1/traces/missing").status_code == 404
        assert client.get("/api/v1/diagnostics/missing").status_code == 404
