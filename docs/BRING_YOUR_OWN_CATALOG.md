# Bring Your Own Catalog

CarbonFactorResolver does not include ecoinvent, customer records, or another commercial
factor database. It resolves structured requests against structured records supplied by the
deployment. Supplying a catalogue does not approve its factors: qualification, human review,
and locking remain separate steps.

The repository includes a deliberately fictional
[`PUBLIC_SYNTHETIC` 20-record example](../data/fixtures/catalog/byoc_public_synthetic_20.json).
Its values exist only to demonstrate software behavior and **must not be used for carbon
accounting**.

## Minimal catalogue envelope

```json
{
  "catalog_version": "your-catalog/v1",
  "database": {
    "name": "authorized-factor-source",
    "sha256": "<64 lowercase hexadecimal characters>"
  },
  "records": [
    {
      "record_id": "source:stable-id",
      "category": "lifecycle_factor",
      "name": "bauxite ore",
      "aliases": ["铝土矿原矿"],
      "primary_value": 0.31,
      "primary_unit": "kgCO2e/kg",
      "subject_type": "raw_material",
      "source_quality_status": "VERIFIED",
      "admission_eligible": true,
      "boundary": "A1",
      "boundary_modules": ["A1"],
      "indicator": "GWP-total",
      "declared_product": "bauxite ore",
      "product_form": "ore",
      "production_process": "mined",
      "source_document_locator": "https://example.invalid/your-evidence",
      "source_document_sha256": "<64 lowercase hexadecimal characters>"
    }
  ]
}
```

Every selectable structured record needs a stable identity, numeric value and unit, subject,
exact boundary, declared product, quality/admission state, evidence locator, and evidence hash.
Geography, year, product form, process and composition should be supplied whenever they affect
applicability. Keep the database hash tied to the exact source snapshot used by the adapter.

## Run the included example

```bash
pip install -e ".[test,api]"
python -m tools.byoc_demo --case exact
python -m tools.byoc_demo --case more-input
python -m tools.byoc_demo --case safe-refusal
```

The three requests demonstrate:

1. exact `bauxite ore` input selects only the original-ore record;
2. generic `spinel` discloses fused and sintered alternatives but returns
   `MORE_INPUT_NEEDED` until the process is supplied;
3. unknown `unobtainium fiber` safely returns no candidate and no invented number.

Run all three and save JSON output for inspection:

```bash
python -m tools.byoc_demo --case all > outputs/byoc-demo.json
```

## File adapter

Use the existing structured catalogue repository and inject the parsed file. CFR runtime code
does not parse PDF, Word, Excel, images, or unstructured evidence.

```python
import json
from pathlib import Path

from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.engine import A1FactorResolutionEngine

path = Path("data/fixtures/catalog/byoc_public_synthetic_20.json")
payload = json.loads(path.read_text(encoding="utf-8"))
repository = HttpCatalogFactorRepository(
    endpoint="file-snapshot://authorized-catalog",
    fetch_json=lambda _endpoint: payload,
)
engine = A1FactorResolutionEngine(local_retrieval=repository)
```

The injected callback is suitable for deterministic file snapshots and tests. It should return
the complete JSON envelope, not an individual record. Use a stable, non-sensitive endpoint
label: it is retained in Trace, so do not put usernames or absolute local paths in it.

## HTTP adapter

For a service that already exposes the same JSON envelope, use its URL directly:

```python
repository = HttpCatalogFactorRepository(
    endpoint="https://catalog.example/api/v1/factors",
    timeout_seconds=10,
    expected_sha256="<pinned snapshot SHA-256>",
)
engine = A1FactorResolutionEngine(local_retrieval=repository)
```

Production deployments should provide authentication, TLS, retry/rate-limit policy, licensed
data access and audit storage outside CFR. A custom repository adapter may implement
`FactorRepositoryPort` when the source cannot provide this envelope; it must still return
provenance-complete `SourceRecord` objects.

## Custom repository adapter

Prefer adapting your transport to the compact envelope and delegating conversion, semantic
indexing, diagnostics, and hash checks to the built-in repository. This keeps custom code from
silently bypassing CFR's record-validation path:

```python
from a1_factor_engine.adapters import HttpCatalogFactorRepository


class AuthorizedCatalogRepository:
    """FactorRepositoryPort backed by an organization's authorized client."""

    def __init__(self, client):
        self._client = client
        self._delegate = HttpCatalogFactorRepository(
            endpoint="adapter://authorized-catalog",
            fetch_json=lambda _endpoint: self._client.export_compact_snapshot(),
        )

    async def search(self, intent):
        return await self._delegate.search(intent)
```

Pass `AuthorizedCatalogRepository(client)` as `local_retrieval` when constructing the engine.
The client must return one complete, versioned envelope per snapshot. If you instead construct
`SourceRecord` and `RetrievalResult` directly, your adapter owns schema validation, a stable
`DatabaseVersionAnchor`, retrieval attempts/observations, source evidence, and deterministic
ordering; add adapter contract tests before deployment.

## Validation

```bash
pytest -q tests/test_byoc_catalog.py
ruff check tools/byoc_demo.py tests/test_byoc_catalog.py
```

The tests prove the example has exactly 20 unique records, contains no licensed/customer data,
converts all 20 records through the real adapter, preserves high-risk near-neighbour separation,
and returns the documented three decisions.

## Common fail-closed outcomes

| Outcome | Typical cause |
|---|---|
| `SOURCE_DOCUMENT_HASH_REQUIRED` | structured record has no valid evidence-document SHA-256 |
| `ADMISSION_REJECTED` | source quality/admission, indicator, declared product, subject, or boundary fails |
| `UNIT_SYNTAX_UNSUPPORTED` | request unit cannot be parsed |
| `UNIT_DIMENSION_MISMATCH` | factor and activity units have incompatible dimensions |
| `MORE_INPUT_NEEDED` | multiple qualified records differ on a decisive process/form/geography/year |
| `SUPPLIER_DATA_REQUIRED` | no defensible record exists in the configured sources |

Do not weaken these checks merely to obtain a result. Inspect the Trace, correct source metadata,
or ask for the missing business attribute.

## Licensing and approval boundary

The repository MIT license does not grant rights to third-party factor data. Confirm the licence
for every connected source and never publish a reconstructable commercial catalogue. See
[`DATA_LICENSE.md`](../DATA_LICENSE.md).

CFR never automatically approves imported records. A recommendation remains subject to human
review; reference-only records require a reasoned override, and only the reviewed decision can
become an immutable locked factor. Formal catalogue admission remains an independent governance
workflow.
