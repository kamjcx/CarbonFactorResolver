from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from a1_factor_engine import CatalogDatasetPolicy, CatalogPolicyBundle
from a1_factor_engine.adapters import (
    DeterministicMaterialUnderstanding,
    HttpCatalogFactorRepository,
    NullFactorRepository,
    NullProxyRepository,
)
from a1_factor_engine.catalog_policy import POLICY_BUNDLE_SCHEMA_VERSION
from a1_factor_engine.cli import main
from a1_factor_engine.graph import GraphInvariantError, GraphState
from a1_factor_engine.integrity import CatalogIntegrityError, catalog_content_sha256
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import ResolutionRequest, RetrievalIntent
from a1_factor_engine.nodes import (
    CandidatePoolNode,
    GapAnalysisNode,
    LocalEvaluateNode,
    LocalRetrievalNode,
    MaterialResolutionNode,
    ProxyEvaluateNode,
    ProxyResolutionNode,
    RankNode,
    ReEvaluateNode,
    ResolutionPlannerNode,
    TopKNode,
    UnitScaleResolutionNode,
)


def _catalog() -> dict[str, object]:
    return {
        "catalog_version": "public-synthetic-v1",
        "database": {"name": "synthetic", "sha256": "a" * 64},
        "records": [{
            "record_id": "synthetic:steel",
            "name": "synthetic steel",
            "primary_value": 1.0,
            "primary_unit": "kgCO2e/kg",
            "category": "lifecycle_factor",
            "subject_type": "raw_material",
            "source_quality_status": "VERIFIED",
            "admission_eligible": True,
            "indicator": "GWP-total",
            "declared_product": "synthetic steel",
            "boundary": "cradle-to-gate",
        }],
    }


@pytest.mark.asyncio
async def test_generic_catalog_repository_has_no_implicit_deployment_policy() -> None:
    catalog = _catalog()
    result = await HttpCatalogFactorRepository(fetch_json=lambda _url: catalog).search(
        RetrievalIntent("synthetic steel", None)
    )

    assert result.records[0].metadata["catalog_dataset_policy_ids"] == "[]"
    assert result.records[0].metadata["catalog_policy_bundle_id"] == ""
    assert result.records[0].metadata["catalog_policy_bundle_signature_status"] == "not_configured"
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).parents[1] / "src" / "a1_factor_engine").glob("*.py")
    )
    assert "REFRACTORY_A1_STANDARD_POLICY" not in source_text
    assert "customer.refractory-draft-first" not in source_text


@pytest.mark.asyncio
async def test_production_approval_bundle_requires_real_signature_verification() -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    digest = catalog_content_sha256(records)
    policy = CatalogDatasetPolicy(
        policy_id="deployment-policy:test-records/v1",
        record_categories=("lifecycle_factor",),
        production_approval_id="deployment-approval:test/v1",
        catalog_content_sha256=digest,
    )
    bundle = CatalogPolicyBundle(
        policy_id="deployment-bundle:test/v1",
        version="1",
        approved_catalog_content_sha256=digest,
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(policy,),
        signature="not-a-real-signature",
    )

    assert bundle.schema_version == POLICY_BUNDLE_SCHEMA_VERSION
    assert len(bundle.content_sha256) == 64
    with pytest.raises(CatalogIntegrityError, match="requires a verified bundle signature"):
        await HttpCatalogFactorRepository(
            fetch_json=lambda _url: catalog,
            policy_bundle=bundle,
            policy_effective_on="2026-09-04",
        ).search(RetrievalIntent("synthetic steel", None))

    observed: list[tuple[bytes, str]] = []

    def verify(payload: bytes, signature: str) -> bool:
        observed.append((payload, signature))
        return signature == "not-a-real-signature" and b'"deployment-bundle:test/v1"' in payload

    result = await HttpCatalogFactorRepository(
        fetch_json=lambda _url: catalog,
        policy_bundle=bundle,
        policy_signature_verifier=verify,
        policy_effective_on="2026-09-04",
    ).search(RetrievalIntent("synthetic steel", None))
    assert observed and observed[0][1] == bundle.signature
    assert result.records[0].metadata["catalog_policy_bundle_signature_status"] == "verified"
    assert result.records[0].metadata["catalog_policy_bundle_effective_on"] == "2026-09-04"


def test_policy_bundle_rejects_malformed_and_reversed_date_windows() -> None:
    common = {
        "policy_id": "deployment-bundle:test/v1",
        "version": "1",
        "approved_catalog_content_sha256": "a" * 64,
        "approved_by": "test-reviewer",
    }
    with pytest.raises(ValueError, match="effective_from must use YYYY-MM-DD"):
        CatalogPolicyBundle(effective_from="20260904", **common)
    with pytest.raises(ValueError, match="effective_from must be a valid calendar date"):
        CatalogPolicyBundle(effective_from="2026-02-30", **common)
    with pytest.raises(ValueError, match="effective_until must be on or after"):
        CatalogPolicyBundle(
            effective_from="2026-09-04",
            effective_until="2026-09-03",
            **common,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effective_from", "effective_until", "effective_on"),
    [
        ("2026-09-05", None, "2026-09-04"),
        ("2026-09-01", "2026-09-03", "2026-09-04"),
    ],
)
async def test_policy_bundle_rejects_future_or_expired_application(
    effective_from: str,
    effective_until: str | None,
    effective_on: str,
) -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    digest = catalog_content_sha256(records)
    policy = CatalogDatasetPolicy(
        policy_id="deployment-policy:test-records/v1",
        production_approval_id="deployment-approval:test/v1",
        catalog_content_sha256=digest,
    )
    bundle = CatalogPolicyBundle(
        policy_id="deployment-bundle:test/v1",
        version="1",
        approved_catalog_content_sha256=digest,
        effective_from=effective_from,
        effective_until=effective_until,
        approved_by="test-reviewer",
        policies=(policy,),
        signature="test-signature",
    )

    with pytest.raises(CatalogIntegrityError, match="is not effective"):
        await HttpCatalogFactorRepository(
            fetch_json=lambda _url: catalog,
            policy_bundle=bundle,
            policy_signature_verifier=lambda _payload, _signature: True,
            policy_effective_on=effective_on,
        ).search(RetrievalIntent("synthetic steel", None))


@pytest.mark.asyncio
async def test_policy_bundle_requires_explicit_replayable_effective_date() -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    digest = catalog_content_sha256(records)
    policy = CatalogDatasetPolicy(
        policy_id="deployment-policy:test-records/v1",
        production_approval_id="deployment-approval:test/v1",
        catalog_content_sha256=digest,
    )
    bundle = CatalogPolicyBundle(
        policy_id="deployment-bundle:test/v1",
        version="1",
        approved_catalog_content_sha256=digest,
        effective_from="2026-09-04",
        approved_by="test-reviewer",
        policies=(policy,),
        signature="test-signature",
    )

    with pytest.raises(CatalogIntegrityError, match="explicit policy_effective_on"):
        await HttpCatalogFactorRepository(
            fetch_json=lambda _url: catalog,
            policy_bundle=bundle,
            policy_signature_verifier=lambda _payload, _signature: True,
        ).search(RetrievalIntent("synthetic steel", None))


@pytest.mark.asyncio
async def test_policy_cache_does_not_reuse_stale_signature_audit_metadata() -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    digest = catalog_content_sha256(records)
    policy = CatalogDatasetPolicy(
        policy_id="deployment-policy:test-records/v1",
        catalog_content_sha256=digest,
    )
    common = {
        "policy_id": "deployment-bundle:test/v1",
        "version": "1",
        "approved_catalog_content_sha256": digest,
        "effective_from": "2026-09-04",
        "approved_by": "test-reviewer",
        "policies": (policy,),
    }
    repository = HttpCatalogFactorRepository(
        fetch_json=lambda _url: catalog,
        policy_bundle=CatalogPolicyBundle(signature="verified-signature", **common),
        policy_signature_verifier=lambda _payload, _signature: True,
        policy_effective_on="2026-09-04",
    )
    first = await repository.search(RetrievalIntent("synthetic steel", None))
    assert first.records[0].metadata["catalog_policy_bundle_signature_status"] == "verified"

    repository.policy_bundle = CatalogPolicyBundle(signature=None, **common)
    repository.policy_signature_verifier = None
    second = await repository.search(RetrievalIntent("synthetic steel", None))

    assert second.records[0].metadata["catalog_policy_bundle_signature_status"] == "unsigned"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node",
    [
        LocalRetrievalNode(NullFactorRepository()),
        LocalEvaluateNode(DeterministicMaterialUnderstanding(), DEFAULT_MATERIAL_REGISTRY),
        GapAnalysisNode(),
        ResolutionPlannerNode(),
        UnitScaleResolutionNode(),
        MaterialResolutionNode(DeterministicMaterialUnderstanding()),
        ProxyResolutionNode(NullProxyRepository()),
        ProxyEvaluateNode(DeterministicMaterialUnderstanding(), DEFAULT_MATERIAL_REGISTRY),
        ReEvaluateNode(0.0),
        CandidatePoolNode(),
        RankNode(),
        TopKNode(),
    ],
)
async def test_graph_nodes_fail_closed_without_normalized_predecessor(node: object) -> None:
    state = GraphState(ResolutionRequest(material_name="synthetic steel", quantity=1))

    with pytest.raises(GraphInvariantError, match="requires normalized activity state"):
        await node.run(state)  # type: ignore[attr-defined]


class _CaptureEngine:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    async def resolve(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return {"request_id": payload["request_id"], "status": "unresolved"}


def test_cli_positional_shortcut_rejects_non_mass_and_mixed_fields() -> None:
    engine = _CaptureEngine()
    for argv in (
        ["resolve", "electricity", "10", "kWh"],
        ["resolve", "steel", "1", "kg", "--unit", "kg"],
    ):
        stdout, stderr = io.StringIO(), io.StringIO()
        assert main(argv, engine=engine, stdout=stdout, stderr=stderr) == 2
        assert json.loads(stdout.getvalue())["detail"]["reason_code"] == "CLI_INVALID_REQUEST"
    assert engine.payloads == []


def test_cli_structured_json_preserves_non_material_contract() -> None:
    engine = _CaptureEngine()
    stdin, stdout = io.StringIO(json.dumps({
        "material_name": "grid electricity",
        "quantity": 10,
        "quantity_unit": "kWh",
        "subject_type": "energy",
        "boundary": "cradle-to-gate",
        "target_factor_unit": "kgCO2e/kWh",
    })), io.StringIO()

    code = main(
        ["resolve", "--input-json", "-"],
        engine=engine,
        stdin=stdin,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 11
    assert engine.payloads[0]["subject_type"] == "energy"
    assert engine.payloads[0]["target_factor_unit"] == "kgCO2e/kWh"


def test_mypy_configuration_has_no_core_ignore_errors_escape_hatch() -> None:
    config = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "ignore_errors = true" not in config
