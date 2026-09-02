from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from a1_factor_engine.models import ResolutionStatus, ResultTier
from tools.byoc_demo import DEFAULT_CATALOG, build_engine, load_catalog, run_cases


def test_byoc_catalog_is_exactly_twenty_public_synthetic_records() -> None:
    payload = load_catalog()
    records = payload["records"]
    assert payload["data_classification"] == "PUBLIC_SYNTHETIC"
    assert payload["contains_licensed_or_customer_data"] is False
    assert "Not valid for carbon accounting" in payload["intended_use"]
    assert len(records) == 20
    assert len({record["record_id"] for record in records}) == 20
    assert {record["category"] for record in records} >= {
        "lifecycle_factor",
        "epd_indicator",
        "energy_factor",
        "combustion_factor",
        "transport_factor",
    }
    assert {record["subject_type"] for record in records} >= {
        "raw_material",
        "finished_product",
        "energy",
        "transport",
        "process",
    }


def test_byoc_catalog_has_complete_synthetic_provenance_and_neighbour_pairs() -> None:
    payload = load_catalog()
    records = payload["records"]
    text = json.dumps(records, ensure_ascii=False).casefold()
    assert "ecoinvent" not in text
    assert "customer" not in text
    assert "d:\\" not in text
    for record in records:
        assert record["source"] == "CFR BYOC public-synthetic example"
        assert record["license"] == "MIT synthetic fixture"
        assert record["source_document_locator"].startswith("https://example.invalid/")
        assert re.fullmatch(r"[0-9a-f]{64}", record["source_document_sha256"])
    identities = {record["record_id"] for record in records}
    assert {
        "byoc:bauxite-ore",
        "byoc:calcined-bauxite-clinker",
        "byoc:high-alumina-brick",
        "byoc:iron-turnings-unsorted",
        "byoc:steel-scrap-baled",
        "byoc:graphite-electrode",
        "byoc:graphite-powder",
        "byoc:road-freight",
        "byoc:rail-freight",
        "byoc:hard-coal-market",
        "byoc:hard-coal-combustion",
    } <= identities


@pytest.mark.asyncio
async def test_byoc_schema_loads_all_records_through_real_catalog_adapter() -> None:
    result = await build_engine().resolve({
        "request_id": "byoc-load-all",
        "material_name": "bauxite ore",
        "quantity": 1,
        "quantity_unit": "kg",
        "subject_type": "raw_material",
        "boundary": "A1",
        "product_form": "ore",
        "production_process": "mined",
        "target_factor_unit": "kgCO2e/kg",
    })
    assert result.status == ResolutionStatus.RECOMMENDATION_READY
    retrieval = next(entry for entry in result.trace.entries if entry.stage == "local_retrieval")
    assert retrieval.details["pipeline_funnel"]["raw_catalog_records"] == 20
    assert retrieval.details["pipeline_funnel"]["converted_records"] == 20
    assert result.candidates[0].source.source_id == "byoc:bauxite-ore"
    assert all(candidate.source.source_id != "byoc:calcined-bauxite-clinker" for candidate in result.candidates)
    assert all(candidate.source.subject_type.value != "finished_product" for candidate in result.candidates)


@pytest.mark.asyncio
async def test_byoc_copyable_examples_match_resolution_contract() -> None:
    payload = await run_cases(("exact", "more-input", "safe-refusal"))
    results = payload["results"]
    assert payload["data_classification"] == "PUBLIC_SYNTHETIC"
    assert payload["not_for_carbon_accounting"] is True
    assert results["exact"]["status"] == "recommendation_ready"
    assert results["exact"]["candidates"][0]["source"]["source_id"] == "byoc:bauxite-ore"
    assert results["more-input"]["status"] == "more_input_needed"
    assert "PROCESS_REQUIRED" in results["more-input"]["reason_codes"]
    assert results["more-input"]["questions"]
    assert results["more-input"]["candidates"] == []
    assert {
        item["source"]["source_id"] for item in results["more-input"]["reviewable_candidates"]
    } == {"byoc:spinel-fused", "byoc:spinel-sintered"}
    assert all(
        item["result_tier"] == ResultTier.REFERENCE_ONLY.value
        for item in results["more-input"]["reviewable_candidates"]
    )
    assert results["safe-refusal"]["status"] == "supplier_data_required"
    assert results["safe-refusal"]["candidates"] == []
    assert results["safe-refusal"]["reviewable_candidates"] == []


def test_byoc_fixture_is_packaged_but_not_a_formal_catalog() -> None:
    assert DEFAULT_CATALOG == Path(__file__).resolve().parents[1] / "data/fixtures/catalog/byoc_public_synthetic_20.json"
