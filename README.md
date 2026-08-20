# A1 Factor Resolution Engine V1

独立、框架无关的 Python 3.11+ Graph Engineering 引擎，用于在本地因子缺失时按 technology-aware Proxy 的有界路径解析 A1 原材料排放因子。

## Quick start

```python
from a1_factor_engine import A1FactorResolutionEngine, ResolutionRequest, SourceRecord, FactorSourceType
from a1_factor_engine.adapters import InMemoryFactorRepository, InMemoryProxyRepository

record = SourceRecord(
    source_id="epd-steel-001", source_type=FactorSourceType.EPD,
    provider="Example EPD registry", locator="https://example.test/epd/001",
    material_name="steel coil", factor_value=1.85, factor_unit="kgCO2e/kg",
    geography="CN", year=2024, product_form="coil",
    composition="carbon steel", production_process="electric arc furnace",
    boundary="cradle-to-gate", citation="EPD-001",
)
engine = A1FactorResolutionEngine(
    local_retrieval=InMemoryFactorRepository([record]),
)
request = ResolutionRequest(
    material_name="steel coil", quantity=1000, quantity_unit="kg",
    geography="CN", year=2024, product_form="coil",
    composition="carbon steel", production_process="electric arc furnace",
)
recommendation = await engine.resolve(request)
for candidate in recommendation.candidates:
    print(
        candidate.factor_value,
        candidate.resolution_type.value,
        candidate.result_tier.value,
        candidate.resolution_strength,
        candidate.provenance.locator,
    )
```

Repositories, material understanding and persistence are async ports. Local retrieval returns both records and the exact database version anchor used for the query.

The formal catalogue API can be connected directly:

```python
from a1_factor_engine.adapters import HttpCatalogFactorRepository

engine = A1FactorResolutionEngine(
    local_retrieval=HttpCatalogFactorRepository(
        endpoint="http://127.0.0.1:5004/api/v2/factors/catalog",
        expected_sha256="799bff31f6cae963d07441b2ac8f7439f27628fef0f9586bbc5f5e38b8434e06",
    ),
)
```

## Graph and routing

`A1ResolutionGraph` makes every state transition explicit:

`INPUT → VALIDATE → NORMALIZE → LOCAL RETRIEVAL → LOCAL EVALUATE → GAP ANALYSIS → RESOLUTION PLANNER`

The planner can execute `UNIT SCALE → REFERENCE FLOW → PROCESS VARIANT → GRADE / COMPOSITION` in dependency order. If direct and same-material resolution are exhausted, it finally visits `MATERIAL RESOLUTION → CLASS-AWARE PROXY → RE-EVALUATE`. All candidates then flow through `CANDIDATE POOL → RANK → TOP-K`.

Retrieval only recalls source records. Gap Analysis explains why a record is not directly usable; Resolution transforms it only with versioned formulas and sourced parameters. Material class remains late and is used primarily for the final material-proxy fallback.

Local and fallback linking use an observable, bounded strategy chain:

`exact_link → synonym_link → related_candidate_recall → class_aware_proxy_link → unresolved`

- `exact_link` compares the normalized canonical material against catalogue name/code.
- `synonym_link` accepts only aliases explicitly supplied by material understanding or registered in catalogue metadata; substring similarity is not a synonym.
- An exact hit stops synonym expansion. Multiple hits remain a candidate set instead of being silently collapsed.
- `related_candidate_recall` is a bounded same-material-family recall for process/grade Gap Analysis; it is not a synonym.
- `class_aware_proxy_link` is the final material-absence fallback and returns technical/generic Top-K candidates.
- Every attempted, skipped and exhausted strategy is recorded in `Trace.link_attempts`.

## Numeric and provenance guarantees

- Original factor values can only enter through `SourceRecord`. Derivation parameters can only enter through traceable `ParameterEvidence`.
- Every derived value is `SourceRecord value(s) + ParameterEvidence value(s) + versioned deterministic formula` and exposes `TransformationStep` lineage.
- `Candidate` must reference the exact `SourceRecord` and matching `Provenance.source_id`.
- Factor and quantity units are converted deterministically (`g`, `kg`, `t`, `lb`; e.g. `kgCO2e/t → kgCO2e/kg`).
- Scoring and stable ranking are deterministic. Semantic/LLM ports may interpret, classify and exclude candidates, but cannot originate numeric values.
- Process, composition, form and material differences become structured gaps instead of immediate rejections. Only invalid/incompatible math, untraceable numerical inputs and double-counting risk hard-block a derived value.
- Ranking first uses `ResolutionType`, then resolution strength, suitability, evidence coverage, source quality, assumptions and stable lineage.
- Candidates are labeled `PRIMARY_RECOMMENDATION`, `USABLE_WITH_ASSUMPTIONS` or `REFERENCE_ONLY`. Resolution strength is an explainable ordering signal, not a probability or approval decision.
- Missing piece-to-mass evidence returns `MORE_INPUT_NEEDED` with the exact required fields; exhausted traceable evidence returns process-model/supplier-data follow-up without retry loops.
- Normalize also emits a request-level `MaterialIdentity`. A broad `steel fiber` request is deliberately returned as `MORE_INPUT_NEEDED` with subtype choices and provisional directions; `MaterialClass` remains a late proxy-only concept.
- Related recall is structured: form-only hits remain `raw_related_hits`/`RecallObservation` and cannot enter the candidate pool. Records are qualified before conversion using `FactorKind`, `indicator`, declared product, boundary and reference-product unit qualifiers. `EMISSION_LIMIT` is never an A1 lifecycle candidate.
- `kgCO2e/t产品` is parsed as mass-per-declared-product; parsing success does not bypass declared-product or factor-kind qualification. `SourceRecord` preserves `factor_kind`, `indicator`, `declared_product` and `boundary_modules` for provenance.

Normalization applies versioned Unicode, case, separator and whitespace rules. Applied rule IDs and semantic remapping are written to Trace so the mapping can be reproduced after rules or catalogue data change.

## Mutable trace and database version anchor

Each resolution creates an appendable `ResolutionTrace`; it is an operational explanation record, not an immutable snapshot. It records:

- formal catalogue name, catalogue version, database SHA-256 and endpoint;
- local records found, including source IDs and observed factor values;
- structured candidate gaps and dependency-ordered resolution plans;
- every unit, reference-flow, process or grade transformation, including source IDs, parameter IDs, Formula ID, inputs and output;
- assumptions, warnings, result tiers and resolution strength;
- the complete deterministic ranking and returned Top-K IDs;
- exact/synonym/related/proxy/unresolved link attempts and remaining evidence gaps;
- later human approval, rejection and lock events.

```python
trace = await engine.trace(request.request_id)
print(trace.database_anchor.database_sha256)
print(trace.latest("local_retrieval").details)
print(trace.latest("top_k").details)
```

Equivalent business requests receive the same request fingerprint even though their run IDs differ. Results before and after a database update can therefore be compared explicitly:

```python
change = await engine.compare_traces(before_request_id, after_request_id)
print(change["database_changed"])
print(change["local_hits_added"], change["local_hits_removed"])
print(change["ranking_before"], change["ranking_after"])
```

## Human approval and locking

```python
approval = await engine.approve(request.request_id, recommendation.candidates[0].candidate_id, "alice")
locked = await engine.lock(request.request_id, recommendation.candidates[0].candidate_id, "alice")
```

`REFERENCE_ONLY` candidates require an explicit override mode and a reason; candidates with assumptions require assumption acceptance:

```python
approval = await engine.approve(
    request.request_id, candidate.candidate_id, "alice",
    note="family reference accepted for screening",
    mode="reference_override",
)
```

Locked factor results are frozen dataclasses and stored immutably. Re-locking the same candidate is idempotent; attempting to lock a different candidate or alter an existing lock raises `ValueError`. The associated Trace remains appendable and is not converted into an immutable Trace snapshot.

## Upstream engineering influences

The refinement adopts selected ideas rather than copying any upstream runtime:

- [FAULDIER](https://github.com/ljlazar/fauldier): explicit language/unit/location harmonization and constrained LLM mapping. V1 adds versioned rule evidence and deterministic resolution strength to address model/run variability.
- [Amazon carbon-assessment-with-ml](https://github.com/amazon-science/carbon-assessment-with-ml): bounded candidate retrieval and ranked recommendation from Flamingo/Parakeet. V1 keeps candidate IDs bounded while deterministic formulas and human approval remain authoritative.
- [Brightway2-io](https://github.com/brightway-lca/brightway2-io): sequential linking strategies and preserved unlinked state. V1 exposes the complete strategy ledger and terminates explicitly at unresolved instead of silently relinking.

The dedicated External Retrieval/Evaluate graph lane remains intentionally absent. Formal database, EPD or literature provenance can still enter through repository ports; Proxy is a fallback after direct local retrieval, not a shortcut around it.

Run tests with `pip install -e .[test]` and `pytest`.

## License

This project is open source under the [MIT License](LICENSE). Factor databases, proprietary datasets, and locally generated outputs are not included in this repository.
