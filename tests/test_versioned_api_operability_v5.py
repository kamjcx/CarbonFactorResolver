from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from a1_factor_engine.cli import main
from a1_factor_engine.operability import (
    API_CONTRACT_VERSION,
    API_VERSION_HEADER,
    CORRELATION_ID_HEADER,
    INTERNAL_SERVER_ERROR,
    REQUEST_VALIDATION_FAILED,
    RESOURCE_NOT_FOUND,
    SERVICE_NOT_READY,
    UNSUPPORTED_MEDIA_TYPE,
    CliExitCode,
)


class ContractEngine:
    def __init__(self, status: str = "recommendation_ready") -> None:
        self.status = status
        self.requests: list[dict[str, object]] = []
        self.results: dict[str, dict[str, object]] = {}

    async def resolve(self, payload):
        captured = dict(payload)
        self.requests.append(captured)
        result = {"request_id": captured["request_id"], "status": self.status}
        self.results[str(captured["request_id"])] = result
        return result

    async def resolve_debug(self, payload):
        return await self.resolve(payload)

    async def state(self, request_id):
        return self.results.get(request_id)


def test_api_v1_openapi_and_error_contract_is_versioned_and_json_only() -> None:
    from a1_factor_engine.api import create_app

    schema = create_app(engine=ContractEngine()).openapi()
    operation = schema["paths"]["/api/v1/resolve"]["post"]
    assert schema["info"]["version"] == API_CONTRACT_VERSION
    assert set(operation["requestBody"]["content"]) == {"application/json"}
    expected = {
        "400": "INVALID_RESOLUTION_REQUEST",
        "409": "RESOLUTION_SCOPE_CONFLICT",
        "415": UNSUPPORTED_MEDIA_TYPE,
        "422": REQUEST_VALIDATION_FAILED,
        "500": INTERNAL_SERVER_ERROR,
    }
    for status, reason in expected.items():
        example = operation["responses"][status]["content"]["application/json"]["example"]
        assert example["detail"]["reason_code"] == reason
        assert example["request_id"]
    assert "RESOLUTION_PAYLOAD_CONFLICT" in operation["x-cfr-reason-codes"]
    encoded = json.dumps(schema).casefold()
    assert "multipart/form-data" not in encoded
    assert "uploadfile" not in encoded


def test_production_image_is_fail_closed_and_compose_demo_is_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'CMD ["cfr", "serve", "--host"' in dockerfile
    assert 'CMD ["cfr", "serve", "--demo"' not in dockerfile
    assert 'command: ["cfr", "serve", "--demo"' in compose


def test_health_is_liveness_and_readiness_fails_closed_or_degrades() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app
    from a1_factor_engine.engine import A1FactorResolutionEngine

    with TestClient(create_app()) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        unavailable = client.get("/readyz")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["reason_code"] == SERVICE_NOT_READY
        assert unavailable.json()["required_unavailable"] == 1

    with TestClient(create_app(engine=A1FactorResolutionEngine())) as client:
        assert client.get("/readyz").status_code == 503

    with TestClient(create_app(
        engine=ContractEngine(),
        required_readiness={"catalog": lambda: {"status": "ok"}},
        optional_readiness={"external": lambda: {"status": "unhealthy"}},
    )) as client:
        degraded = client.get("/readyz")
        assert degraded.status_code == 200
        assert degraded.json() == {
            "status": "degraded",
            "required_total": 2,
            "required_unavailable": 0,
            "optional_unavailable": 1,
        }

    with TestClient(create_app(
        engine=ContractEngine(), required_readiness={"catalog": lambda: False}
    )) as client:
        required_failure = client.get("/readyz")
        assert required_failure.status_code == 503
        assert required_failure.json()["required_unavailable"] == 1


@pytest.mark.parametrize(
    "probe_result",
    [
        {},
        {"status": "down"},
        {"status": "mystery"},
        {"available": False, "status": "ok"},
        {"available": True, "status": "unhealthy"},
    ],
)
def test_required_readiness_mapping_fails_closed(probe_result: dict[str, object]) -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    with TestClient(create_app(
        engine=ContractEngine(), required_readiness={"catalog": lambda: probe_result}
    )) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == SERVICE_NOT_READY
    assert response.json()["required_unavailable"] == 1


@pytest.mark.parametrize(
    "probe_result",
    [
        {"status": "ok"},
        {"status": "ready"},
        {"status": "available"},
        {"available": True},
        {"available": True, "status": "ok"},
    ],
)
def test_required_readiness_mapping_accepts_only_explicit_positive_state(
    probe_result: dict[str, object],
) -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    with TestClient(create_app(
        engine=ContractEngine(), required_readiness={"catalog": lambda: probe_result}
    )) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_request_and_correlation_id_flow_through_response_state_and_read() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    engine = ContractEngine()
    with TestClient(create_app(engine=engine)) as client:
        first = client.post(
            "/api/v1/resolve",
            headers={"x-request-id": "caller-request-1"},
            json={"material_name": "钢纤维", "quantity": 1},
        )
        second = client.post(
            "/api/v1/resolve",
            headers={"x-request-id": "caller-request-1"},
            json={"material_name": "钢纤维", "quantity": 1},
        )
        read = client.get("/api/v1/resolutions/caller-request-1")

    assert first.status_code == second.status_code == read.status_code == 200
    assert first.json() == second.json() == read.json()
    assert first.json()["request_id"] == "caller-request-1"
    assert first.headers[CORRELATION_ID_HEADER] == "caller-request-1"
    assert first.headers[API_VERSION_HEADER] == API_CONTRACT_VERSION
    assert len(engine.requests) == 1
    assert engine.requests[0]["request_id"] == "caller-request-1"


def test_request_id_replay_requires_the_same_canonical_payload() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    engine = ContractEngine()
    app = create_app(engine=engine)
    with TestClient(app) as client:
        first = client.post("/api/v1/resolve", json={
            "request_id": "stable-replay", "quantity": 1, "material_name": "steel",
        })
        same_different_key_order = client.post("/api/v1/resolve", json={
            "material_name": "steel", "request_id": "stable-replay", "quantity": 1,
        })
        conflict = client.post("/api/v1/resolve", json={
            "request_id": "stable-replay", "material_name": "aluminium", "quantity": 1,
        })

    assert first.status_code == same_different_key_order.status_code == 200
    assert first.json() == same_different_key_order.json()
    assert len(engine.requests) == 1
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason_code"] == "RESOLUTION_PAYLOAD_CONFLICT"


@pytest.mark.asyncio
async def test_concurrent_request_id_replay_is_atomic_for_same_or_conflicting_payload() -> None:
    import httpx

    from a1_factor_engine.api import create_app

    class SlowEngine(ContractEngine):
        async def resolve(self, payload):
            self.requests.append(dict(payload))
            await asyncio.sleep(0.02)
            result = {"request_id": payload["request_id"], "status": self.status}
            self.results[str(payload["request_id"])] = result
            return result

    same_engine = SlowEngine()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(engine=same_engine)), base_url="http://test"
    ) as client:
        same = await asyncio.gather(*(
            client.post("/api/v1/resolve", json={
                "request_id": "concurrent-same", "material_name": "steel", "quantity": 1,
            })
            for _ in range(2)
        ))
    assert [item.status_code for item in same] == [200, 200]
    assert same[0].json() == same[1].json()
    assert len(same_engine.requests) == 1

    conflict_engine = SlowEngine()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(engine=conflict_engine)), base_url="http://test"
    ) as client:
        different = await asyncio.gather(
            client.post("/api/v1/resolve", json={
                "request_id": "concurrent-conflict", "material_name": "steel", "quantity": 1,
            }),
            client.post("/api/v1/resolve", json={
                "request_id": "concurrent-conflict", "material_name": "aluminium", "quantity": 1,
            }),
        )
    assert sorted(item.status_code for item in different) == [200, 409]
    assert next(item for item in different if item.status_code == 409).json()["detail"][
        "reason_code"
    ] == "RESOLUTION_PAYLOAD_CONFLICT"
    assert len(conflict_engine.requests) == 1


def test_invalid_correlation_id_is_not_reflected() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    unsafe = "token=secret C:\\private\\catalog.db"
    with TestClient(create_app(engine=ContractEngine())) as client:
        response = client.post(
            "/api/v1/resolve", headers={"x-request-id": unsafe},
            json={"material_name": "steel", "quantity": 1},
        )
    assert response.status_code == 200
    assert unsafe not in response.text
    assert unsafe not in response.headers[CORRELATION_ID_HEADER]


def test_api_content_validation_not_found_and_internal_failure_are_stable() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    secret = "token=do-not-leak C:\\internal\\resolver.py:77"

    class Exploding(ContractEngine):
        async def resolve(self, _payload):
            raise RuntimeError(secret)

    with TestClient(create_app(engine=Exploding()), raise_server_exceptions=False) as client:
        wrong_media = client.post("/api/v1/resolve", content="{}", headers={"content-type": "text/plain"})
        malformed = client.post(
            "/api/v1/resolve", content="{", headers={"content-type": "application/json"}
        )
        missing = client.get("/api/v1/resolutions/missing")
        failed = client.post("/api/v1/resolve", json={"material_name": "steel", "quantity": 1})

    assert wrong_media.status_code == 415
    assert wrong_media.json()["detail"]["reason_code"] == UNSUPPORTED_MEDIA_TYPE
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["reason_code"] == REQUEST_VALIDATION_FAILED
    assert missing.status_code == 404
    assert missing.json()["detail"]["reason_code"] == RESOURCE_NOT_FOUND
    assert failed.status_code == 500
    assert failed.json()["detail"]["reason_code"] == INTERNAL_SERVER_ERROR
    assert secret not in wrong_media.text + malformed.text + missing.text + failed.text


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("recommendation_ready", CliExitCode.SUCCESS),
        ("reference_review_required", CliExitCode.SUCCESS),
        ("more_input_needed", CliExitCode.MORE_INPUT),
        ("unresolved", CliExitCode.UNRESOLVED),
        ("supplier_data_required", CliExitCode.UNRESOLVED),
    ],
)
def test_cli_exit_codes_are_stable_and_stdout_is_machine_json(status, expected) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["resolve", "steel", "1", "kg"],
        engine=ContractEngine(status), stdout=stdout, stderr=stderr,
    )
    assert code == int(expected)
    assert json.loads(stdout.getvalue())["status"] == status
    assert stderr.getvalue() == ""


def test_cli_reads_utf8_json_from_stdin_and_requires_explicit_demo() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    engine = ContractEngine()
    code = main(
        ["resolve", "--input-json", "-"], engine=engine,
        stdin=io.StringIO('{"material_name":"钢纤维","quantity":1,"quantity_unit":"kg"}'),
        stdout=stdout, stderr=stderr,
    )
    assert code == 0
    assert engine.requests[0]["material_name"] == "钢纤维"
    assert json.loads(stdout.getvalue())["status"] == "recommendation_ready"

    refused_out, refused_err = io.StringIO(), io.StringIO()
    refused = main(
        ["resolve", "steel", "1", "kg"], stdout=refused_out, stderr=refused_err
    )
    assert refused == int(CliExitCode.INVALID_REQUEST)
    assert json.loads(refused_out.getvalue())["detail"]["reason_code"] == "CLI_INVALID_REQUEST"
    assert refused_err.getvalue() == "cfr: invalid request\n"


def test_cli_invalid_and_internal_failures_are_sanitized() -> None:
    secret = "Bearer super-secret C:\\Users\\private\\catalog.db"

    class Exploding(ContractEngine):
        async def resolve(self, _payload):
            raise RuntimeError(secret)

    bad_out, bad_err = io.StringIO(), io.StringIO()
    invalid = main(
        ["resolve", "--input-json", "-"], engine=ContractEngine(),
        stdin=io.StringIO("[1,2]"), stdout=bad_out, stderr=bad_err,
    )
    assert invalid == int(CliExitCode.INVALID_REQUEST)
    assert json.loads(bad_out.getvalue())["detail"]["reason_code"] == "CLI_INVALID_REQUEST"

    fail_out, fail_err = io.StringIO(), io.StringIO()
    failed = main(
        ["resolve", "steel", "1", "kg"], engine=Exploding(),
        stdout=fail_out, stderr=fail_err,
    )
    assert failed == int(CliExitCode.INTERNAL_FAILURE)
    combined = fail_out.getvalue() + fail_err.getvalue()
    assert json.loads(fail_out.getvalue())["detail"]["reason_code"] == "CLI_INTERNAL_FAILURE"
    assert secret not in combined
    assert "C:\\Users" not in combined


def test_formal_cli_never_calls_debug_or_accepts_min_score() -> None:
    class SpyEngine(ContractEngine):
        def __init__(self):
            super().__init__()
            self.debug_calls = 0

        async def resolve_debug(self, _payload):
            self.debug_calls += 1
            raise AssertionError("formal CLI must not call resolve_debug")

    engine = SpyEngine()
    stdout, stderr = io.StringIO(), io.StringIO()
    assert main(
        ["resolve", "steel", "1", "kg"], engine=engine, stdout=stdout, stderr=stderr
    ) == 0
    assert len(engine.requests) == 1
    assert engine.debug_calls == 0
    assert "min_score" not in engine.requests[0]

    rejected_out, rejected_err = io.StringIO(), io.StringIO()
    assert main(
        ["resolve", "steel", "1", "kg", "--min-score", "0"],
        engine=engine, stdout=rejected_out, stderr=rejected_err,
    ) == int(CliExitCode.INVALID_REQUEST)
    assert len(engine.requests) == 1
    assert engine.debug_calls == 0
