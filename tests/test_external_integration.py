from __future__ import annotations

import pytest

from a1_factor_engine import A1FactorResolutionEngine, ResolutionStatus
from a1_factor_engine.external_connectors import (
    FixtureExternalConnector,
    StructuredEPDEvidenceExtractor,
)


def _engine() -> A1FactorResolutionEngine:
    return A1FactorResolutionEngine(
        external_connectors=(FixtureExternalConnector(),),
        external_extractor=StructuredEPDEvidenceExtractor(),
    )


@pytest.mark.asyncio
async def test_generic_aluminium_discovers_routes_but_requires_choice():
    result = await _engine().resolve(
        {"request_id": "external-generic", "material_name": "aluminium", "quantity": 1}
    )

    assert result.status == ResolutionStatus.MORE_INPUT_NEEDED
    discovery = [event for event in result.trace.entries if event.stage == "external_discovery"]
    assert discovery
    assert set(discovery[-1].details["source_ids"]) == {
        "fixture-al-primary-a1a3",
        "fixture-al-secondary-a1a3",
    }
    assert "fixture-alumina-a1a3" not in discovery[-1].details["source_ids"]


@pytest.mark.asyncio
async def test_primary_aluminium_ingot_enters_external_lane_with_hash_provenance():
    result = await _engine().resolve(
        {
            "request_id": "external-primary-ingot",
            "material_name": "primary aluminium ingot",
            "quantity": 1,
            "production_process": "primary aluminium production",
        }
    )

    assert result.status in {
        ResolutionStatus.RECOMMENDATION_READY,
        ResolutionStatus.REFERENCE_REVIEW_REQUIRED,
    }
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate.source.source_id == "fixture-al-primary-a1a3"
    assert candidate.source.source_document_sha256
    assert len(candidate.source.source_document_sha256) == 64
    assert candidate.source.metadata["parser_version"] == "structured-epd/v1"
    assert all(item.source.source_id != "fixture-al-secondary-a1a3" for item in result.candidates)


def test_default_api_reports_fixture_connector_health():
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    response = TestClient(create_app()).get("/api/v1/connectors/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["connectors"]["FixtureExternalConnector"]["available"] is True


@pytest.mark.asyncio
async def test_connector_discovery_failure_does_not_block_later_connector():
    class BrokenConnector:
        async def discover(self, _intent):
            class TransportFailure(Exception):
                pass

            raise TransportFailure("upstream unavailable")

    engine = A1FactorResolutionEngine(
        external_connectors=(BrokenConnector(), FixtureExternalConnector()),
        external_extractor=StructuredEPDEvidenceExtractor(),
    )
    result = await engine.resolve(
        {
            "request_id": "external-failure-isolation",
            "material_name": "primary aluminium ingot",
            "quantity": 1,
            "production_process": "primary aluminium production",
        }
    )

    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    assert result.candidates[0].source.source_id == "fixture-al-primary-a1a3"
    failures = [
        item for item in result.trace.entries
        if item.stage == "external_discovery" and item.details.get("reason_code")
    ]
    assert failures[-1].details["reason_code"] == "TransportFailure"


def test_default_benchmark_api_rejects_paths_outside_configured_root(tmp_path):
    from fastapi.testclient import TestClient

    from a1_factor_engine.api import create_app

    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    response = TestClient(create_app()).post(
        "/api/v1/benchmarks/runs", json={"path": str(outside)}
    )

    assert response.status_code == 403
