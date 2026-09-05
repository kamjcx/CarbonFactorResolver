from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from a1_factor_engine import (
    A1FactorResolutionEngine,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    SourceRecord,
)
from a1_factor_engine.adapters import InMemoryFactorRepository
from a1_factor_engine.operability import (
    API_CONTRACT_VERSION,
    API_VERSION_HEADER,
    CORRELATION_ID_HEADER,
    INTERNAL_SERVER_ERROR,
    REQUEST_ID_HEADER,
    REQUEST_VALIDATION_FAILED,
)


def _engine() -> A1FactorResolutionEngine:
    source = SourceRecord(
        source_id="public-synthetic-steel",
        source_type=FactorSourceType.LOCAL_DATABASE,
        provider="PUBLIC_SYNTHETIC",
        locator="file:///private/runtime/catalog.json",
        material_name="steel",
        factor_value=1.2,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2025,
        boundary="cradle-to-gate",
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.RAW_MATERIAL,
        indicator="GWP-total",
        declared_product="steel",
        boundary_modules=("A1", "A2", "A3"),
        catalog_locator="C:/private/catalog.db",
        source_document_sha256="ab" * 32,
        page="7",
        table="factor-table",
        row="steel-row",
        metadata={"internal_pipeline": "must-not-leak"},
    )
    return A1FactorResolutionEngine(
        local_retrieval=InMemoryFactorRepository((source,))
    )


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


@pytest.mark.parametrize(
    "payload",
    [
        {"material_name": "steel", "quantity": True},
        {"material_name": "steel", "quantity": False},
        {"material_name": None, "quantity": 1},
        {"material_name": "", "quantity": 1},
        {"material_name": "steel", "quantity": "1"},
        {"material_name": "steel", "quantity": 1, "year": True},
        {"material_name": "steel", "quantity": 1, "top_k": True},
        {"material_name": "steel", "quantity": 1, "subject_type": "material"},
        {"material_name": "steel", "quantity": 1, "unknown": "field"},
        {"material_name": "steel", "quantity": 1, "unit_conversion_evidence": None},
        {"material_name": "steel", "quantity": 1, "unit_conversion_evidence": {}},
        {
            "material_name": "steel",
            "quantity": 1,
            "unit_conversion_evidence": {
                "evidence_id": "evidence",
                "version": "v1",
                "source_canonical_unit": "m3",
                "target_canonical_unit": "Nm3",
            },
        },
        {
            "material_name": "steel",
            "quantity": 1,
            "unit_conversion_evidence": {
                "evidence_id": "evidence",
                "version": "v1",
                "source_canonical_unit": "m3",
                "target_canonical_unit": "Nm3",
                "multiplier": 1.04,
                "internal_note": "not allowed",
            },
        },
        {
            "material_name": "steel",
            "quantity": 1,
            "unit_conversion_evidence": {
                "evidence_id": "evidence",
                "version": "v1",
                "source_canonical_unit": "m3",
                "target_canonical_unit": "Nm3",
                "multiplier": True,
            },
        },
        {"material_name": "steel", "quantity": 1, "unit_conversion_evidence": []},
    ],
)
def test_public_resolve_rejects_ambiguous_or_malformed_json(payload: object) -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    with TestClient(create_app(engine=_engine())) as client:
        response = client.post("/api/v1/resolve", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == REQUEST_VALIDATION_FAILED
    assert response.json()["error"] == response.json()["detail"]


@pytest.mark.parametrize("numeric", ["NaN", "Infinity", "-Infinity"])
def test_public_resolve_rejects_non_finite_json_numbers(numeric: str) -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    body = '{"material_name":"steel","quantity":' + numeric + "}"
    with TestClient(create_app(engine=_engine())) as client:
        response = client.post(
            "/api/v1/resolve",
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == REQUEST_VALIDATION_FAILED


def test_complete_http_evidence_is_mapped_then_independently_domain_validated() -> None:
    from decimal import Decimal

    from a1_factor_engine.api_contracts import ResolutionRequestDTO
    from a1_factor_engine.models import ResolutionRequest

    dto = ResolutionRequestDTO.model_validate({
        "material_name": "process gas",
        "quantity": 2,
        "quantity_unit": "m3",
        "target_factor_unit": "kgCO2e/Nm3",
        "unit_conversion_evidence": {
            "evidence_id": "meter-condition-v1",
            "version": "2026-09",
            "source_canonical_unit": "m3",
            "target_canonical_unit": "Nm3",
            "multiplier": 1.04,
        },
    })
    domain = ResolutionRequest.from_mapping(dto.to_domain_mapping())

    assert domain.quantity == 2.0
    assert domain.unit_conversion_evidence is not None
    assert domain.unit_conversion_evidence.multiplier == Decimal("1.04")


def test_production_openapi_uses_closed_json_request_and_public_response_schemas() -> None:
    from a1_factor_engine.api import create_app

    schema = create_app(engine=_engine()).openapi()
    operation = schema["paths"]["/api/v1/resolve"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert request_schema["$ref"].endswith("/ResolutionRequestDTO")
    assert response_schema["$ref"].endswith("/PublicRecommendationDTO")
    request_component = schema["components"]["schemas"]["ResolutionRequestDTO"]
    assert request_component["additionalProperties"] is False
    assert set(request_component["required"]) == {"material_name", "quantity"}
    assert "min_score" not in request_component["properties"]
    encoded = json.dumps(schema).casefold()
    assert "uploadfile" not in encoded
    assert "multipart/form-data" not in encoded


def test_production_resolve_replay_and_read_use_the_same_recursive_allowlist() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    engine = _engine()
    payload = {
        "request_id": "public-contract",
        "material_name": "steel",
        "quantity": 1,
        "geography": "CN",
        "year": 2025,
        "subject_type": "raw_material",
    }
    with TestClient(create_app(engine=engine)) as client:
        created = client.post("/api/v1/resolve", json=payload)
        replayed = client.post("/api/v1/resolve", json=payload)
        read = client.get("/api/v1/resolutions/public-contract")

    assert created.status_code == replayed.status_code == read.status_code == 200
    assert created.json() == replayed.json() == read.json()
    forbidden = {
        "trace",
        "entries",
        "diagnostic_candidates",
        "missing_gaps",
        "accounting_assignments",
        "created_at",
        "revision",
        "database_anchor_sha256",
        "registry_anchor_sha256",
        "policy_anchor_sha256",
        "dimensions",
        "metadata",
        "locator",
        "catalog_locator",
        "transformation_steps",
        "parameter_evidence_ids",
        "base_source_ids",
        "total_emissions_kgco2e",
    }
    assert not (_walk_keys(created.json()) & forbidden)
    assert created.json()["candidates"][0]["source"]["source_id"] == "public-synthetic-steel"
    assert created.json()["candidates"][0]["source"]["source_document_sha256"] == "ab" * 32


def test_injected_nested_internal_fields_cannot_escape_through_any_public_path() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    class LeakyEngine:
        def __init__(self) -> None:
            self.resolved = False
            self.result = {
                "request_id": "mapping-leak",
                "status": "unresolved",
                "trace": {"entries": [{"metadata": {"secret": "never"}}]},
                "diagnostic_candidates": [{"locator": "C:/private/catalog.db"}],
                "created_at": "internal-clock",
                "runtime": {"policy_anchor_sha256": "cd" * 32},
            }

        async def resolve(self, _payload):
            self.resolved = True
            return self.result

        async def state(self, _request_id):
            return self.result if self.resolved else None

    engine = LeakyEngine()
    payload = {"request_id": "mapping-leak", "material_name": "steel", "quantity": 1}
    with TestClient(create_app(engine=engine)) as client:
        created = client.post("/api/v1/resolve", json=payload)
        replayed = client.post("/api/v1/resolve", json=payload)
        read = client.get("/api/v1/resolutions/mapping-leak")

    assert created.status_code == replayed.status_code == read.status_code == 200
    assert created.json() == replayed.json() == read.json()
    assert not (
        _walk_keys(created.json())
        & {"trace", "entries", "metadata", "diagnostic_candidates", "locator", "runtime"}
    )


def test_admin_debug_retains_full_diagnostics_as_an_explicit_contrast() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import AuthorizationContext, create_admin_app

    async def allow(_headers, _permission):
        return AuthorizationContext(
            "reviewer",
            "tenant",
            "project",
            ("resolve:debug",),
        )

    with TestClient(create_admin_app(engine=_engine(), authorizer=allow)) as client:
        response = client.post("/api/v1/debug/resolve", json={
            "request_id": "admin-debug-contract",
            "material_name": "steel",
            "quantity": 1,
            "geography": "CN",
            "year": 2025,
            "subject_type": "raw_material",
        })

    assert response.status_code == 200
    assert "trace" in response.json()
    assert "diagnostic_candidates" in response.json()
    assert "created_at" in response.json()


def _assert_error_contract(response, expected_reason: str) -> None:
    assert response.headers[API_VERSION_HEADER] == API_CONTRACT_VERSION
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers[CORRELATION_ID_HEADER]
    assert response.headers[REQUEST_ID_HEADER] == response.headers[CORRELATION_ID_HEADER]
    payload = response.json()
    assert payload["api_version"] == API_CONTRACT_VERSION
    assert payload["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert payload["correlation_id"] == response.headers[CORRELATION_ID_HEADER]
    assert payload["error"] == payload["detail"]
    assert payload["error"]["reason_code"] == expected_reason


def test_every_public_error_class_has_stable_headers_and_non_leaking_envelope() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app
    from a1_factor_engine.operability import (
        RESOURCE_NOT_FOUND,
        UNSUPPORTED_MEDIA_TYPE,
    )

    secret = "token=never-return C:/private/runtime.py:77"

    class InvalidEngine:
        async def state(self, _request_id):
            return None

        async def resolve(self, _payload):
            raise ValueError(secret)

    class ExplodingEngine(InvalidEngine):
        async def resolve(self, _payload):
            raise RuntimeError(secret)

    with TestClient(create_app(engine=InvalidEngine())) as client:
        invalid = client.post("/api/v1/resolve", json={"material_name": "steel", "quantity": 1})
        not_found = client.get("/api/v1/resolutions/missing")
        media = client.post(
            "/api/v1/resolve", content="{}", headers={"content-type": "text/plain"}
        )
        validation = client.post("/api/v1/resolve", json={"material_name": None, "quantity": 1})
    with TestClient(create_app(engine=ExplodingEngine()), raise_server_exceptions=False) as client:
        internal = client.post("/api/v1/resolve", json={"material_name": "steel", "quantity": 1})

    _assert_error_contract(invalid, "INVALID_RESOLUTION_REQUEST")
    _assert_error_contract(not_found, RESOURCE_NOT_FOUND)
    _assert_error_contract(media, UNSUPPORTED_MEDIA_TYPE)
    _assert_error_contract(validation, REQUEST_VALIDATION_FAILED)
    _assert_error_contract(internal, INTERNAL_SERVER_ERROR)
    assert secret not in invalid.text + not_found.text + media.text + validation.text + internal.text


def test_replay_conflict_uses_the_same_public_error_contract() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import RESOLUTION_PAYLOAD_CONFLICT, create_app

    with TestClient(create_app(engine=_engine())) as client:
        first = client.post("/api/v1/resolve", json={
            "request_id": "conflict-contract", "material_name": "steel", "quantity": 1,
        })
        conflict = client.post("/api/v1/resolve", json={
            "request_id": "conflict-contract", "material_name": "other", "quantity": 1,
        })

    assert first.status_code == 200
    assert conflict.status_code == 409
    _assert_error_contract(conflict, RESOLUTION_PAYLOAD_CONFLICT)


def test_readiness_error_and_scope_documentation_preserve_the_public_contract() -> None:
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app
    from a1_factor_engine.operability import SERVICE_NOT_READY

    with TestClient(create_app()) as client:
        readiness = client.get("/readyz")

    assert readiness.status_code == 503
    _assert_error_contract(readiness, SERVICE_NOT_READY)
    assert readiness.json()["required_unavailable"] == 1

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    contract = (root / "docs" / "CFR_API_SAFETY_CONTRACT.md").read_text(encoding="utf-8")
    for document in (readme, contract):
        assert "trusted single" in document
        assert "multi-tenant" in document
