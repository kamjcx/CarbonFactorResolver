"""Portfolio fault-injection suite; production code remains unchanged."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from a1_factor_engine import A1FactorResolutionEngine, ResolutionStatus
from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.external_connectors import (
    ExternalDiscoveryRef,
    ExternalDocument,
    FixtureExternalConnector,
    StructuredEPDEvidenceExtractor,
)
from a1_factor_engine.models import RetrievalIntent

LOCAL_DATABASE_SHA = "1" * 64
INJECTED_SECRET = "portfolio-test-secret"


def valid_item(**changes):
    item = {
        "source_id": "fault-valid-primary",
        "document_kind": "structured_epd",
        "subject_type": "raw_material",
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "source_type": "external_database",
        "material_name": "primary aluminium",
        "aliases": ["primary aluminium ingot"],
        "factor_value": 8.4,
        "factor_unit": "kgCO2e/kg",
        "indicator": "GWP-total",
        "declared_product": "1 kg primary aluminium ingot",
        "boundary": "cradle-to-gate",
        "boundary_modules": ["A1", "A2", "A3"],
        "source_locator": "fixture://fault/primary",
        "evidence_locator": "fixture://fault/primary#GWP-total",
        "production_process": "primary aluminium production",
    }
    item.update(changes)
    return item


def valid_local_catalog(**changes):
    payload = {
        "catalog_version": "portfolio-fault-fixture/v1",
        "database": {"name": "portfolio-fault-fixture", "sha256": LOCAL_DATABASE_SHA},
        "records": [],
    }
    payload.update(changes)
    return payload


def raising_fetch(exception):
    def fetch(_endpoint):
        raise exception

    return fetch


def local_repository(fetch_json, *, expected_sha256=LOCAL_DATABASE_SHA):
    return HttpCatalogFactorRepository(
        endpoint="fixture://fault/local-catalog",
        expected_sha256=expected_sha256,
        fetch_json=fetch_json,
    )


def local_fault(name):
    if name == "timeout":
        return local_repository(raising_fetch(TimeoutError(f"catalog timeout {INJECTED_SECRET}")))
    if name == "connection_failure":
        return local_repository(raising_fetch(ConnectionError(f"catalog unavailable {INJECTED_SECRET}")))
    if name == "malformed_payload":
        return local_repository(lambda _endpoint: valid_local_catalog(records="not-a-list"))
    if name == "sha_mismatch":
        return local_repository(lambda _endpoint: valid_local_catalog(), expected_sha256="2" * 64)
    raise AssertionError(f"unsupported local fault: {name}")


class RaisingConnector:
    def __init__(self, exception_type):
        self.exception_type = exception_type

    async def discover(self, _intent):
        raise self.exception_type("injected connector failure")


class StructuredConnector:
    def __init__(self, item, *, malformed=False, sha_mismatch=False):
        self.item = item
        self.malformed = malformed
        self.sha_mismatch = sha_mismatch

    async def discover(self, _intent):
        raw = self._raw()
        digest = hashlib.sha256(raw).hexdigest()
        return (ExternalDiscoveryRef(
            source_id=str(self.item.get("source_id", "fault-source")),
            provider="Fault injection fixture",
            locator="fixture://fault/document",
            document_kind="structured_epd",
            expected_content_sha256=digest,
        ),)

    async def fetch(self, ref):
        raw = self._raw()
        digest = hashlib.sha256(raw).hexdigest()
        return ExternalDocument(
            ref=ref, content=raw,
            content_sha256=("0" * 64 if self.sha_mismatch else digest),
            retrieved_at=datetime.now(UTC),
        )

    def _raw(self):
        if self.malformed:
            return b"{not-json"
        return json.dumps(
            self.item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()


async def resolve_with(*connectors):
    return await A1FactorResolutionEngine(
        external_connectors=connectors,
        external_extractor=StructuredEPDEvidenceExtractor(),
    ).resolve({
        "material_name": "primary aluminium ingot",
        "quantity": 1,
        "production_process": "primary aluminium production",
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "exception_type"),
    [("timeout", TimeoutError), ("http_429", type("HTTP429", (Exception,), {})),
     ("http_500", type("HTTP500", (Exception,), {}))],
)
async def test_discovery_failures_are_fail_closed_and_traceable(name, exception_type):
    result = await resolve_with(RaisingConnector(exception_type))
    assert result.status != ResolutionStatus.ERROR, name
    assert not result.candidates
    assert not result.reviewable_candidates
    failures = [entry for entry in result.trace.entries if entry.details.get("reason_code")]
    assert failures and failures[-1].details["reason_code"] == exception_type.__name__


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "connector"),
    [
        ("malformed_json", StructuredConnector(valid_item(), malformed=True)),
        ("sha_mismatch", StructuredConnector(valid_item(), sha_mismatch=True)),
        ("missing_boundary", StructuredConnector(valid_item(boundary="", boundary_modules=[]))),
        ("missing_subject", StructuredConnector(valid_item(subject_type=""))),
    ],
)
async def test_invalid_structured_evidence_never_enters_candidates(name, connector):
    result = await resolve_with(connector)
    assert result.status != ResolutionStatus.ERROR, name
    assert not result.candidates
    assert not result.reviewable_candidates
    rejected = [
        entry for entry in result.trace.entries
        if entry.stage == "external_fetch" and entry.details.get("reason_code")
    ]
    assert rejected and rejected[-1].details["reason_code"] == "InvalidExternalEvidence"


@pytest.mark.asyncio
async def test_rejected_source_is_not_admitted():
    result = await resolve_with(StructuredConnector(valid_item(source_quality_status="REJECTED")))
    assert not result.candidates
    assert not result.reviewable_candidates


@pytest.mark.asyncio
async def test_duplicate_source_ids_do_not_duplicate_ranked_candidates():
    item = valid_item()
    result = await resolve_with(StructuredConnector(item), StructuredConnector(item))
    ids = [item.source.source_id for item in (*result.candidates, *result.reviewable_candidates)]
    assert ids.count("fault-valid-primary") <= 1


@pytest.mark.asyncio
async def test_partial_connector_failure_preserves_verified_fallback():
    result = await resolve_with(RaisingConnector(TimeoutError), FixtureExternalConnector())
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].source.source_id == "fixture-al-primary-a1a3"
    failures = [entry for entry in result.trace.entries if entry.details.get("reason_code")]
    assert any(entry.details["reason_code"] == "TimeoutError" for entry in failures)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "exception_type"),
    [
        ("timeout", TimeoutError),
        ("connection_failure", ConnectionError),
        ("malformed_payload", ValueError),
        ("sha_mismatch", ValueError),
    ],
)
async def test_local_catalog_faults_are_explicit_at_repository_boundary(name, exception_type):
    repository = local_fault(name)
    intent = RetrievalIntent(canonical_name="primary aluminium", base_entity_id="mat.aluminium")

    with pytest.raises(exception_type):
        await repository.search(intent)


@pytest.mark.parametrize("name", ["timeout", "connection_failure"])
def test_api_contains_local_catalog_transport_failures_without_5xx_or_disclosure(name):
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "tester", "tenant", "project", ("resolve:execute", "trace:read")
        )
    app = create_admin_app(
        engine=A1FactorResolutionEngine(local_retrieval=local_fault(name)), authorizer=allow
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        request_id = f"portfolio-local-{name}"
        response = client.post(
            "/api/v1/resolve",
            json={
                "request_id": request_id,
                "material_name": "primary aluminium",
                "quantity": 1,
            },
        )
        trace_response = client.get(f"/api/v1/traces/{request_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == ResolutionStatus.SUPPLIER_DATA_REQUIRED.value
    assert not payload["candidates"]
    assert not payload["reviewable_candidates"]
    assert INJECTED_SECRET not in response.text
    assert "Traceback" not in response.text

    assert trace_response.status_code == 200
    trace_payload = trace_response.json()
    failure = next(
        entry for entry in trace_payload["entries"] if entry["stage"] == "local_retrieval"
    )
    assert failure["details"]["reason_code"] in {"TimeoutError", "ConnectionError"}
    assert INJECTED_SECRET not in json.dumps(trace_payload)


@pytest.mark.parametrize("name", ["malformed_payload", "sha_mismatch"])
def test_api_contains_local_catalog_data_faults_without_5xx_or_disclosure(name):
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    app = create_app(engine=A1FactorResolutionEngine(local_retrieval=local_fault(name)))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/resolve",
            json={
                "request_id": f"portfolio-local-{name}",
                "material_name": "primary aluminium",
                "quantity": 1,
            },
        )

    assert response.status_code < 500
    assert INJECTED_SECRET not in response.text
    assert "Traceback" not in response.text


def test_connector_health_redacts_exception_secrets_and_stack_details():
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    def unhealthy_catalog():
        raise RuntimeError(f"dsn=postgres://user:{INJECTED_SECRET}@catalog internal.py:42")

    with TestClient(
        create_app(connector_health={"catalog": unhealthy_catalog}),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/v1/connectors/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert INJECTED_SECRET not in response.text
    assert "postgres://" not in response.text
    assert "internal.py" not in response.text
    assert "Traceback" not in response.text
    assert response.json() == {"status": "degraded"}


def test_non_mapping_connector_health_failure_is_sanitized_and_degraded():
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    def unhealthy_catalog():
        raise RuntimeError(f"token={INJECTED_SECRET} internal.py:42")

    with TestClient(
        create_app(connector_health=unhealthy_catalog),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/v1/connectors/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded"}
    assert INJECTED_SECRET not in response.text


def test_resolve_validation_error_does_not_reflect_internal_exception_text():
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    class InvalidResolver:
        async def resolve(self, _payload):
            raise ValueError(f"token={INJECTED_SECRET} internal.py:42")

    with TestClient(create_app(engine=InvalidResolver())) as client:
        response = client.post("/api/v1/resolve", json={"material_name": "steel"})

    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "INVALID_RESOLUTION_REQUEST"
    assert INJECTED_SECRET not in response.text
    assert "internal.py" not in response.text
