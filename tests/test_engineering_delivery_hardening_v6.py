from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from a1_factor_engine import CatalogDatasetPolicy, CatalogPolicyBundle
from a1_factor_engine.adapters import HttpCatalogFactorRepository, NullFactorRepository
from a1_factor_engine.catalog_policy import POLICY_BUNDLE_SCHEMA_VERSION
from a1_factor_engine.cli import main
from a1_factor_engine.graph import GraphInvariantError, GraphState
from a1_factor_engine.integrity import CatalogIntegrityError, catalog_content_sha256
from a1_factor_engine.models import ResolutionRequest, RetrievalIntent
from a1_factor_engine.nodes import LocalRetrievalNode, UnitScaleResolutionNode


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
        ).search(RetrievalIntent("synthetic steel", None))

    observed: list[tuple[bytes, str]] = []

    def verify(payload: bytes, signature: str) -> bool:
        observed.append((payload, signature))
        return signature == "not-a-real-signature" and b'"deployment-bundle:test/v1"' in payload

    result = await HttpCatalogFactorRepository(
        fetch_json=lambda _url: catalog,
        policy_bundle=bundle,
        policy_signature_verifier=verify,
    ).search(RetrievalIntent("synthetic steel", None))
    assert observed and observed[0][1] == bundle.signature
    assert result.records[0].metadata["catalog_policy_bundle_signature_status"] == "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node",
    [LocalRetrievalNode(NullFactorRepository()), UnitScaleResolutionNode()],
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
