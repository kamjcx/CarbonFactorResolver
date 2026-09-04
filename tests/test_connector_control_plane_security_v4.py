from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from a1_factor_engine.connector_security import (
    CONNECTOR_FETCH_FAILED,
    CONNECTOR_REDIRECT_REJECTED,
    CONNECTOR_RESPONSE_TOO_COMPLEX,
    CONNECTOR_RESPONSE_TOO_LARGE,
    CONNECTOR_TIMEOUT,
    CONNECTOR_URL_REJECTED,
    ConnectorLimits,
    ConnectorSecurityError,
    OutboundRequestPolicy,
    StructuredFetchResponse,
    bound_transport,
    redact_sensitive_text,
)
from a1_factor_engine.external_connectors import OpenEPDConnector
from a1_factor_engine.models import RetrievalIntent

PUBLIC = ("93.184.216.34",)


def public_resolver(_host: str, _port: int):
    return PUBLIC


def query() -> RetrievalIntent:
    return RetrievalIntent(canonical_name="steel", base_entity_id=None)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.test",
        "file:///etc/passwd",
        "https://user:secret@api.example.test",
        "https://127.0.0.1",
        "https://[::1]",
        "https://10.0.0.1",
        "https://172.16.0.1",
        "https://192.168.0.1",
        "https://169.254.169.254/latest/meta-data",
        "https://[fe80::1]",
    ],
)
def test_outbound_policy_rejects_unsafe_urls(url: str) -> None:
    policy = OutboundRequestPolicy(base_url=url, resolver=public_resolver)
    with pytest.raises(ConnectorSecurityError) as caught:
        policy.validate_url(url)
    assert caught.value.reason_code == CONNECTOR_URL_REJECTED


def test_outbound_policy_rejects_unallowlisted_and_dns_rebound_hosts() -> None:
    policy = OutboundRequestPolicy(
        base_url="https://api.example.test",
        resolver=lambda _host, _port: ("10.42.0.8",),
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        policy.validate_url("https://api.example.test/epds")
    assert caught.value.reason_code == CONNECTOR_URL_REJECTED
    with pytest.raises(ConnectorSecurityError):
        policy.validate_url("https://attacker.example/steal", resolve_dns=False)
    with pytest.raises(ConnectorSecurityError):
        policy.validate_url("https://api.example.test:444/epds", resolve_dns=False)


async def test_same_origin_succeeds_and_cross_origin_redirect_is_rejected() -> None:
    seen = []

    @bound_transport
    async def same_origin(url, headers, context):
        seen.append((url, headers))
        if url.startswith("https://api.example.test/epds"):
            return StructuredFetchResponse(
                {}, url, redirect_to="https://api.example.test/v2/epds",
                peer_ip=context.route.resolved_ips[0],
            )
        return StructuredFetchResponse(
            {"results": []}, "https://api.example.test/v2/epds",
            peer_ip=context.route.resolved_ips[0],
        )

    connector = OpenEPDConnector(
        api_key="test-token",
        base_url="https://api.example.test",
        discovery_fetcher=same_origin,
        document_fetcher=same_origin,
        resolver=public_resolver,
    )
    assert await connector.discover(query()) == ()
    assert len(seen) == 2
    assert all(item[1]["Authorization"] == "Bearer test-token" for item in seen)

    @bound_transport
    async def cross_origin(url, headers, context):
        return StructuredFetchResponse(
            {}, url, redirect_to="https://attacker.example/result",
            peer_ip=context.route.resolved_ips[0],
        )

    connector = OpenEPDConnector(
        api_key="test-token",
        base_url="https://api.example.test",
        discovery_fetcher=cross_origin,
        document_fetcher=cross_origin,
        allowed_hosts=("attacker.example",),
        resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_REDIRECT_REJECTED


async def test_bearer_is_not_forwarded_to_allowlisted_document_origin() -> None:
    calls = []

    @bound_transport
    async def discovery(url, headers, context):
        return StructuredFetchResponse(
            {"results": [{"id": "one", "url": "https://documents.example/one"}]},
            url,
            peer_ip=context.route.resolved_ips[0],
        )

    @bound_transport
    async def document(url, headers, context):
        calls.append(headers)
        return StructuredFetchResponse(
            {"source_id": "one"}, url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="test-token",
        base_url="https://api.example.test",
        discovery_fetcher=discovery,
        document_fetcher=document,
        allowed_hosts=("documents.example",),
        resolver=public_resolver,
    )
    ref = (await connector.discover(query()))[0]
    await connector.fetch(ref)
    assert "Authorization" not in calls[0]


async def test_size_timeout_and_document_count_limits_are_stable() -> None:
    limits = ConnectorLimits(max_response_bytes=8, max_documents=1, total_timeout_seconds=0.1)

    @bound_transport
    async def oversized(_url, _headers, context):
        return StructuredFetchResponse(
            b'{"results":[]}', _url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=oversized, document_fetcher=oversized,
        resolver=public_resolver, limits=limits,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_RESPONSE_TOO_LARGE

    @bound_transport
    async def too_many(_url, _headers, context):
        return StructuredFetchResponse(
            {"results": [{"id": "1"}, {"id": "2"}]},
            _url,
            peer_ip=context.route.resolved_ips[0],
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=too_many, document_fetcher=too_many,
        resolver=public_resolver, limits=ConnectorLimits(max_documents=1),
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_RESPONSE_TOO_COMPLEX

    @bound_transport
    async def slow(_url, _headers, context):
        await asyncio.sleep(0.05)
        return StructuredFetchResponse(
            {"results": []}, _url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=slow, document_fetcher=slow,
        resolver=public_resolver,
        limits=ConnectorLimits(total_timeout_seconds=0.001),
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_TIMEOUT


async def test_transport_receives_distinct_timeouts_and_streaming_aborts() -> None:
    observed = []

    async def chunks():
        yield b'{"res'
        yield b'ults":[]}'

    @bound_transport
    async def transport(_url, _headers, context):
        observed.append((context.connect_timeout_seconds, context.read_timeout_seconds))
        return StructuredFetchResponse(chunks(), _url, peer_ip=context.route.resolved_ips[0])

    limits = ConnectorLimits(
        connect_timeout_seconds=1.25,
        read_timeout_seconds=2.5,
        max_response_bytes=8,
    )
    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=transport, document_fetcher=transport,
        resolver=public_resolver, limits=limits,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_RESPONSE_TOO_LARGE
    assert observed == [(1.25, 2.5)]


def test_redaction_removes_tokens_queries_and_internal_addresses() -> None:
    value = redact_sensitive_text(
        "Authorization: Bearer unit-test-secret "
        "https://api.example.test/epds?token=unit-test-secret "
        "internal=10.0.0.9 ipv6=fe80::1 loopback=::1"
    )
    assert "unit-test-secret" not in value
    assert "?" not in value
    assert "10.0.0.9" not in value
    assert "fe80::1" not in value
    assert "::1" not in value


async def test_transport_exception_is_replaced_with_stable_non_sensitive_error() -> None:
    @bound_transport
    async def failing(_url, _headers, _context):
        raise RuntimeError(
            "Authorization: Bearer unit-test-secret https://10.0.0.9/?token=unit-test-secret"
        )

    connector = OpenEPDConnector(
        api_key="unit-test-secret", base_url="https://api.example.test",
        discovery_fetcher=failing, document_fetcher=failing, resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_FETCH_FAILED
    assert "unit-test-secret" not in str(caught.value)
    assert "10.0.0.9" not in str(caught.value)


async def test_connection_peer_must_match_the_prevalidated_public_route() -> None:
    @bound_transport
    async def rebound(url, _headers, _context):
        return StructuredFetchResponse({"results": []}, url, peer_ip="10.0.0.8")

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=rebound, document_fetcher=rebound,
        resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError, match="peer address"):
        await connector.discover(query())


async def test_public_bound_peer_succeeds_and_redirect_hop_is_re_resolved() -> None:
    resolutions = iter((("93.184.216.34",), ("93.184.216.35",)))
    bound_routes = []

    def changing_resolver(_host, _port):
        return next(resolutions)

    @bound_transport
    async def transport(url, _headers, context):
        bound_routes.append(context.route.resolved_ips)
        if len(bound_routes) == 1:
            return StructuredFetchResponse(
                {}, url, redirect_to="/v2/epds", peer_ip=context.route.resolved_ips[0]
            )
        return StructuredFetchResponse(
            {"results": []}, url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=transport, document_fetcher=transport,
        resolver=changing_resolver,
    )
    assert await connector.discover(query()) == ()
    assert bound_routes == [("93.184.216.34",), ("93.184.216.35",)]


def test_legacy_unbound_fetchers_are_not_live_ready() -> None:
    async def legacy(_url, _headers):
        return {"results": []}

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=legacy, document_fetcher=legacy,
        resolver=public_resolver,
    )
    assert connector.health().available is False
    assert "bind validated" in connector.health().reason


async def test_sync_blocking_transport_and_stream_failure_are_bounded_and_redacted() -> None:
    @bound_transport
    def blocking(_url, _headers, context):
        time.sleep(0.05)
        return StructuredFetchResponse(
            {"results": []}, _url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=blocking, document_fetcher=blocking,
        resolver=public_resolver, limits=ConnectorLimits(total_timeout_seconds=0.001),
    )
    started = time.monotonic()
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_TIMEOUT
    assert time.monotonic() - started < 0.04

    async def broken_stream():
        yield b'{"res'
        raise RuntimeError("Bearer stream-secret http://10.0.0.8/private")

    @bound_transport
    async def streaming(url, _headers, context):
        return StructuredFetchResponse(
            broken_stream(), url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=streaming, document_fetcher=streaming,
        resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_FETCH_FAILED
    assert "stream-secret" not in str(caught.value)


async def test_sync_dns_resolution_is_bounded_and_does_not_block_event_loop() -> None:
    heartbeat = asyncio.Event()

    def blocking_resolver(_host, _port):
        time.sleep(0.06)
        return PUBLIC

    @bound_transport
    async def transport(url, _headers, context):
        return StructuredFetchResponse(
            {"results": []}, url, peer_ip=context.route.resolved_ips[0]
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=transport, document_fetcher=transport,
        resolver=blocking_resolver, limits=ConnectorLimits(total_timeout_seconds=0.005),
    )

    async def tick():
        await asyncio.sleep(0.001)
        heartbeat.set()

    started = time.monotonic()
    task = asyncio.create_task(tick())
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    await task
    assert caught.value.reason_code == CONNECTOR_TIMEOUT
    assert heartbeat.is_set()
    assert time.monotonic() - started < 0.04


async def test_deep_json_and_transport_followed_redirects_fail_stably() -> None:
    deep = ("[" * 1200 + "0" + "]" * 1200).encode()

    @bound_transport
    async def deep_transport(url, _headers, context):
        return StructuredFetchResponse(deep, url, peer_ip=context.route.resolved_ips[0])

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=deep_transport, document_fetcher=deep_transport,
        resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_RESPONSE_TOO_COMPLEX

    @bound_transport
    async def auto_followed(url, _headers, context):
        return StructuredFetchResponse(
            {"results": []}, url,
            redirect_chain=("https://api.example.test/hidden",),
            peer_ip=context.route.resolved_ips[0],
        )

    connector = OpenEPDConnector(
        api_key="token", base_url="https://api.example.test",
        discovery_fetcher=auto_followed, document_fetcher=auto_followed,
        resolver=public_resolver,
    )
    with pytest.raises(ConnectorSecurityError) as caught:
        await connector.discover(query())
    assert caught.value.reason_code == CONNECTOR_REDIRECT_REJECTED


def _allow_all():
    from a1_factor_engine.api import AuthorizationContext

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "actor", "tenant", "project",
            (
                "resolve:execute", "resolution:read", "resolve:debug", "trace:read",
                "diagnostics:read", "benchmark:execute", "benchmark:read",
            ),
        )

    return allow


def test_production_openapi_has_no_control_plane_and_admin_fails_closed() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_admin_app, create_app

    production = create_app()
    paths = set(production.openapi()["paths"])
    assert "/api/v1/resolve" in paths
    assert not any(token in path for path in paths for token in ("benchmark", "debug", "trace", "diagnostic"))
    with TestClient(create_admin_app()) as client:
        assert client.get("/api/v1/traces/secret").status_code == 403
        assert client.post("/api/v1/benchmarks/runs", json={"path": "../secret.jsonl"}).status_code == 403

    async def incomplete(_headers, _permission):
        from a1_factor_engine.api import AuthorizationContext

        return AuthorizationContext("", "tenant", "project", ("trace:read",))

    with TestClient(create_admin_app(authorizer=incomplete)) as client:
        assert client.get("/api/v1/traces/secret").status_code == 403


def test_benchmark_empty_roots_traversal_and_oversize_fail_closed(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_admin_app

    class Runner:
        async def run(self, _path):
            raise AssertionError("rejected datasets must never execute")

    with TestClient(create_admin_app(benchmark_runner=Runner(), authorizer=_allow_all())) as client:
        assert client.post("/api/v1/benchmarks/runs", json={"path": "../x.jsonl"}).status_code == 403

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    oversized = allowed / "large.jsonl"
    oversized.write_text(json.dumps({"padding": "x" * 100}), encoding="utf-8")
    target = allowed / "target.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    symlink = allowed / "linked.jsonl"
    try:
        symlink.symlink_to(target)
    except OSError:
        symlink = None
    app = create_admin_app(
        benchmark_runner=Runner(), benchmark_roots=(allowed,), authorizer=_allow_all(),
        max_benchmark_bytes=16,
    )
    with TestClient(app) as client:
        assert client.post("/api/v1/benchmarks/runs", json={"path": str(outside)}).status_code == 403
        assert client.post("/api/v1/benchmarks/runs", json={"path": str(oversized)}).status_code == 413
        if symlink is not None:
            assert client.post(
                "/api/v1/benchmarks/runs", json={"path": str(symlink)}
            ).status_code == 400


def test_admin_objects_are_tenant_project_scoped_and_cache_bytes_are_bounded(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")

    async def authorize(headers, _permission):
        return AuthorizationContext(
            "actor", headers.get("x-tenant", "tenant-a"), "project",
            ("resolve:execute", "resolution:read", "trace:read", "diagnostics:read",
             "benchmark:execute", "benchmark:read"),
        )

    class Runner:
        async def run(self, _path):
            return {"run_id": "tenant-run", "padding": "x" * 64}

        def compare(self, _base, _candidate):
            return {"ok": True}

    app = create_admin_app(
        benchmark_runner=Runner(), benchmark_roots=(tmp_path,), authorizer=authorize,
        max_benchmark_cache_bytes=4096,
    )
    with TestClient(app) as client:
        headers_a = {"x-tenant": "tenant-a"}
        headers_b = {"x-tenant": "tenant-b"}
        resolved = client.post(
            "/api/v1/resolve", headers=headers_a,
            json={"request_id": "tenant-resolution", "material_name": "unknown", "quantity": 1},
        )
        assert resolved.status_code == 200
        assert client.get("/api/v1/traces/tenant-resolution", headers=headers_a).status_code == 200
        assert client.get("/api/v1/traces/tenant-resolution", headers=headers_b).status_code == 404
        assert client.get("/api/v1/diagnostics/tenant-resolution", headers=headers_b).status_code == 404
        assert client.get("/api/v1/resolutions/tenant-resolution", headers=headers_b).status_code == 404
        conflicting = client.post(
            "/api/v1/resolve", headers=headers_b,
            json={"request_id": "tenant-resolution", "material_name": "other", "quantity": 1},
        )
        assert conflicting.status_code == 409
        assert conflicting.json()["detail"]["reason_code"] == "RESOLUTION_SCOPE_CONFLICT"
        run = client.post(
            "/api/v1/benchmarks/runs", headers=headers_a, json={"path": str(dataset)}
        )
        assert run.status_code == 201
        same_id_other_scope = client.post(
            "/api/v1/benchmarks/runs", headers=headers_b, json={"path": str(dataset)}
        )
        assert same_id_other_scope.status_code == 201
        assert same_id_other_scope.json()["run_id"] == "tenant-run"
        assert client.get("/api/v1/benchmarks/runs/tenant-run", headers=headers_a).status_code == 200
        assert client.get("/api/v1/benchmarks/runs/tenant-run", headers=headers_b).status_code == 200
        assert client.get(
            "/api/v1/benchmarks/compare?base=tenant-run&candidate=tenant-run", headers=headers_b
        ).status_code == 200

    oversized_app = create_admin_app(
        benchmark_runner=Runner(), benchmark_roots=(tmp_path,), authorizer=authorize,
        max_benchmark_cache_bytes=32,
    )
    with TestClient(oversized_app) as client:
        response = client.post(
            "/api/v1/benchmarks/runs", headers={"x-tenant": "tenant-a"},
            json={"path": str(dataset)},
        )
    assert response.status_code == 413


def test_authorizer_exception_and_incomplete_scope_fail_closed_without_disclosure() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    async def failing(_headers, _permission):
        raise RuntimeError("Bearer auth-secret https://10.0.0.8/internal")

    with TestClient(create_admin_app(authorizer=failing), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/traces/anything")
    assert response.status_code == 403
    assert "auth-secret" not in response.text
    assert "10.0.0.8" not in response.text

    for context in (
        AuthorizationContext(" ", "tenant", "project", ("trace:read",)),
        AuthorizationContext("actor", " ", "project", ("trace:read",)),
        AuthorizationContext("actor", "tenant", " ", ("trace:read",)),
    ):
        async def incomplete(_headers, _permission, value=context):
            return value

        with TestClient(create_admin_app(authorizer=incomplete)) as client:
            assert client.get("/api/v1/traces/anything").status_code == 403
