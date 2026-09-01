import hashlib
import json

import pytest

from a1_factor_engine.external_connectors import (
    ExternalDiscoveryRef,
    ExternalDocument,
    FixtureExternalConnector,
    InvalidExternalEvidence,
    OpenEPDConnector,
    PublicStructuredEPDConnector,
    StructuredEPDEvidenceExtractor,
)
from a1_factor_engine.models import FactorKind, RetrievalIntent


def intent(name: str, *aliases: str) -> RetrievalIntent:
    return RetrievalIntent(canonical_name=name, base_entity_id=None, aliases=aliases)


@pytest.mark.parametrize(
    "name,source_id",
    [
        ("primary aluminium", "fixture-al-primary-a1a3"),
        ("secondary aluminium", "fixture-al-secondary-a1a3"),
        ("alumina", "fixture-alumina-a1a3"),
    ],
)
async def test_fixture_discovers_fetches_and_extracts_hashed_provenance(name, source_id):
    connector = FixtureExternalConnector()
    extractor = StructuredEPDEvidenceExtractor()

    refs = await connector.discover(intent(name))
    assert [ref.source_id for ref in refs] == [source_id]
    document = await connector.fetch(refs[0])
    records = await extractor.extract(document, intent(name))

    assert document.content_sha256 == hashlib.sha256(document.content).hexdigest()
    assert records[0].source_document_sha256 == document.content_sha256
    assert records[0].metadata["snapshot_sha256"] == refs[0].snapshot_sha256
    assert records[0].metadata["parser_version"] == "structured-epd/v1"
    assert records[0].metadata["evidence_locator"]
    assert records[0].factor_kind is FactorKind.EPD_INDICATOR
    assert records[0].boundary_modules == ("A1", "A2", "A3")


async def test_fixture_returns_no_answer_instead_of_a_guess():
    assert await FixtureExternalConnector().discover(intent("unobtainium foam")) == ()


async def test_declared_product_substring_cannot_create_a_reviewed_alias():
    item = {
        "source_id": "substring-bypass",
        "material_name": "foo material concentrate",
        "factor_value": 1.0,
        "factor_unit": "kgCO2e/kg",
        "indicator": "GWP-total",
        "declared_product": "not foo material waste",
        "boundary": "product stage",
        "boundary_modules": ["A1"],
        "source_locator": "https://example.invalid/substring-bypass",
        "evidence_locator": "https://example.invalid/substring-bypass#GWP",
        "subject_type": "raw_material",
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
    }
    content = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(content).hexdigest()
    ref = ExternalDiscoveryRef(
        "substring-bypass",
        "test",
        "https://example.invalid/substring-bypass",
        "structured_epd",
        digest,
    )
    document = ExternalDocument(
        ref,
        content,
        digest,
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    records = await StructuredEPDEvidenceExtractor().extract(document, intent("foo material"))

    assert records[0].metadata["aliases"] == "[]"
    assert records[0].metadata["match_strategy"] == "related_candidate_recall"
    assert records[0].metadata["match_proof"] == "catalogue_name_or_alias"


async def test_missing_openepd_credentials_are_explicit_and_nonblocking(monkeypatch):
    monkeypatch.delenv("OPENEPD_API_KEY", raising=False)
    monkeypatch.delenv("OPENEPD_BASE_URL", raising=False)
    calls = []

    async def should_not_run(*args):
        calls.append(args)
        raise AssertionError("network adapter must not be called")

    connector = OpenEPDConnector(discovery_fetcher=should_not_run, document_fetcher=should_not_run)
    health = connector.health()

    assert health.available is False
    assert health.status == "unavailable"
    assert "OPENEPD_API_KEY" in health.reason
    assert await connector.discover(intent("primary aluminium")) == ()
    assert calls == []


async def test_public_snapshot_injected_fetcher_must_preserve_pinned_content():
    async def tampering_fetcher(ref):
        return {"source_id": ref.source_id, "factor_value": 999}

    connector = PublicStructuredEPDConnector(fetcher=tampering_fetcher)
    ref = (await connector.discover(intent("alumina")))[0]
    with pytest.raises(InvalidExternalEvidence, match="differs from pinned snapshot"):
        await connector.fetch(ref)


@pytest.mark.parametrize(
    "update,error",
    [
        ({"factor_value": -1}, "finite and non-negative"),
        ({"factor_value": float("nan")}, "finite and non-negative"),
        ({"factor_unit": "points/kg"}, "not parseable"),
        ({"indicator": "ODP"}, "GWP indicator"),
        ({"declared_product": ""}, "declared_product"),
        ({"boundary_modules": []}, "boundary and boundary_modules"),
        ({"evidence_locator": ""}, "source and evidence locators"),
        ({"subject_type": ""}, "subject_type"),
        ({"source_quality_status": ""}, "source_quality_status"),
        ({"admission_eligible": "yes"}, "admission_eligible"),
    ],
)
async def test_invalid_evidence_is_rejected_before_source_record(update, error):
    item = {
        "source_id": "invalid",
        "material_name": "alumina",
        "factor_value": 1.0,
        "factor_unit": "kgCO2e/kg",
        "indicator": "GWP-total",
        "declared_product": "1 kg alumina",
        "boundary": "product stage",
        "boundary_modules": ["A1"],
        "source_locator": "fixture://invalid",
        "evidence_locator": "fixture://invalid#GWP",
        "subject_type": "raw_material",
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
    }
    item.update(update)
    content = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=True).encode()
    digest = hashlib.sha256(content).hexdigest()
    ref = ExternalDiscoveryRef("invalid", "test", "fixture://invalid", "structured_epd", digest)
    document = ExternalDocument(ref, content, digest, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))

    with pytest.raises(InvalidExternalEvidence, match=error):
        await StructuredEPDEvidenceExtractor().extract(document, intent("alumina"))


async def test_search_summary_document_is_never_accepted_as_factor_evidence():
    content = b'{"factor_value":1}'
    digest = hashlib.sha256(content).hexdigest()
    ref = ExternalDiscoveryRef("summary", "search", "https://example.invalid/search", "search_summary", digest)
    document = ExternalDocument(ref, content, digest, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    with pytest.raises(InvalidExternalEvidence, match="search summaries"):
        await StructuredEPDEvidenceExtractor().extract(document, intent("alumina"))


async def test_malformed_snapshot_hash_is_rejected_even_if_copied_to_document():
    item = {
        "source_id": "forged",
        "material_name": "alumina",
        "factor_value": 1.0,
        "factor_unit": "kgCO2e/kg",
        "indicator": "GWP-total",
        "declared_product": "1 kg alumina",
        "boundary": "product stage",
        "boundary_modules": ["A1"],
        "source_locator": "fixture://forged",
        "evidence_locator": "fixture://forged#GWP",
    }
    content = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(content).hexdigest()
    ref = ExternalDiscoveryRef(
        "forged", "test", "fixture://forged", "structured_epd", digest, "not-a-sha"
    )
    document = ExternalDocument(
        ref,
        content,
        digest,
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        "not-a-sha",
    )
    with pytest.raises(InvalidExternalEvidence, match="snapshot SHA-256 is malformed"):
        await StructuredEPDEvidenceExtractor().extract(document, intent("alumina"))
