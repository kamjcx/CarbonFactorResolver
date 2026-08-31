# CarbonFactorResolver

CarbonFactorResolver（CFR，碳因子解析引擎）是独立、框架无关的 Python 3.11+ Graph Engineering 引擎，用于对原材料、能源与工艺相关的碳因子进行有证据约束的检索、语义匹配、代理解析和审计追溯。

## End-to-end demo

Version 0.13.1 adds exact lifecycle-stage qualification, subject and source-quality admission gates, a hardened true-data ingestion acceptance, and an independently frozen real-query holdout. The default demo uses only clearly labelled public-synthetic fixtures; it never auto-approves a factor.

```bash
pip install -e ".[test,api]"
cfr resolve --material "aluminium" --quantity 1 --unit t
cfr resolve --material "primary aluminium ingot" --quantity 1 --unit t --process "primary aluminium production"
cfr benchmark run data/benchmarks/factorbench_v1.jsonl
cfr serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for Query, Benchmark, and Compare views. See [architecture](docs/CFR_ARCHITECTURE.md), [evaluation methodology](docs/CFR_EVALUATION_METHODOLOGY.md), [external-source policy](docs/CFR_EXTERNAL_SOURCE_POLICY.md), and the [aluminium root-cause case study](docs/CFR_ALUMINIUM_RETRIEVAL_ROOT_CAUSE.md).

## Quick start

```python
from a1_factor_engine import A1FactorResolutionEngine, ResolutionRequest, SourceRecord, FactorKind, FactorSourceType
from a1_factor_engine.adapters import InMemoryFactorRepository, InMemoryProxyRepository

record = SourceRecord(
    source_id="epd-steel-001", source_type=FactorSourceType.EPD,
    provider="Example EPD registry", locator="https://example.test/epd/001",
    material_name="steel coil", factor_value=1.85, factor_unit="kgCO2e/kg",
    geography="CN", year=2024, product_form="coil",
    composition="carbon steel", production_process="electric arc furnace",
    boundary="cradle-to-gate", citation="EPD-001",
    factor_kind=FactorKind.EPD_INDICATOR, indicator="GWP-total",
    subject_type="finished_product", source_quality_status="verified",
    admission_eligible=True,
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
- A qualified exact candidate stops lower-priority evaluation. Invalid exact rows remain auditable and allow a registered alias to continue.
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
- Process derivation requires non-negative common upstream, complete target-energy shares, explicit process inclusion and explicitly scoped parameter evidence.
- Direct, Proxy and Grade anchors use one policy-driven qualification engine. Proxy family/form/process/grade differences become gaps, while lifecycle meaning, indicator, boundary, unit and provenance stay strict.
- Proxy candidates make at most one dependency-ordered pass through Unit/Reference Flow/Grade/Process resolution; no retry loop is introduced.
- Ranking first uses `ResolutionType`, then resolution strength, suitability, evidence coverage, source quality, assumptions and stable lineage.
- Candidates are labeled `PRIMARY_RECOMMENDATION`, `USABLE_WITH_ASSUMPTIONS` or `REFERENCE_ONLY`. Resolution strength is an explainable ordering signal, not a probability or approval decision.
- Missing piece-to-mass evidence returns `MORE_INPUT_NEEDED` with the exact required fields; exhausted traceable evidence returns process-model/supplier-data follow-up without retry loops.
- Normalize also emits a request-level `MaterialIdentity`. A broad `steel fiber` request is deliberately returned as `MORE_INPUT_NEEDED` with subtype choices and provisional directions; `MaterialClass` remains a late proxy-only concept.
- Related recall is structured: form-only hits remain `raw_related_hits`/`RecallObservation` and cannot enter the candidate pool. Records are qualified before conversion using `FactorKind`, `indicator`, declared product, boundary and reference-product unit qualifiers. `EMISSION_LIMIT` is never an A1 lifecycle candidate.
- `kgCO2e/t产品` is parsed as mass-per-declared-product; parsing success does not bypass declared-product or factor-kind qualification. `SourceRecord` preserves `factor_kind`, `indicator`, `declared_product` and `boundary_modules` for provenance.

Normalization applies versioned Unicode, case, separator and whitespace rules. Applied rule IDs and semantic remapping are written to Trace so the mapping can be reproduced after rules or catalogue data change.

## Entity-first semantic resolution

Version 0.7 upgrades the deterministic semantic layer from name-first matching to entity-first retrieval:

`normalized text → MaterialMention → IdentityResolution → RetrievalIntent → Semantic Index`

- The parser assigns explicit roles such as `BASE_ENTITY`, `ENTITY_TYPE`, `PROCESS`, `PRODUCT_FORM`, `GRADE`, `PURITY` and `CONSTITUENT`; modifiers constrain identity but do not replace the base entity.
- Requests and source records use the same entity registry and Semantic Index. The index is rebuilt in process when the catalogue or registry digest changes and records both anchors in Trace.
- Exact primary names and reviewed aliases can become direct candidates. Same-entity variants are admitted only when both sides have a resolved, equal `base_entity_id`; lexical CJK overlap is never sufficient.
- Composite materials preserve multiple constituents. For example, `莫来石-碳化硅砖` retains both mullite and silicon-carbide entity IDs rather than being flattened to mullite.
- `金属铝`, `氧化铝`, `铝合金`, `金属硅`, `二氧化硅` and `碳化硅` resolve to distinct identities. A `金属铝` query therefore cannot recall silicon or alumina merely because of shared characters.
- A generic material with multiple route variants, such as primary and secondary aluminium, returns `MORE_INPUT_NEEDED` with an explicit route choice instead of silently selecting a factor.
- Only `ACTIVE` reviewed rules affect runtime identity or retrieval. `DRAFT`, `DEPRECATED` and `REJECTED` rules are ignored.
- Unknown names may be sent to an optional `MaterialRuleSuggestionPort`. Its structured output remains a `DRAFT` review artifact and never becomes an active identity automatically.
- Trace records the structured mention, identity proof, retrieval intent, registry/index versions, link attempts, candidate admissions and hard exclusions.
- The registry contains no emission-factor values. Numeric values still enter only through provenance-bearing `SourceRecord` or `ParameterEvidence`.
- New vocabulary is released as reviewed registry data without changing Graph routing.

For example, `电熔莫来石` resolves to base entity `mat.mineral.mullite` plus process `electrofused`; `烧结莫来石` is therefore recalled only as a same-entity process variant and enters Process Gap analysis, while `电熔刚玉` is excluded despite sharing the process word `电熔`.

The complete Chinese implementation contract is in `docs/CFR_SEMANTIC_RESOLUTION_V2_IMPLEMENTATION_ZH.md`.

## Entity-scoped numeric purity grades

Version 0.8 adds a deterministic numeric-token layer on top of entity-first resolution:

- After the material entity is resolved, standalone `70`, `80` and `90` may bind to a reviewed entity-scoped `PurityGradeSchema`. For example, magnesia uses MgO as its organization-default basis and spinel uses Al2O3.
- A bare grade is an `IMPLICIT_GRADE_CLASS`; it is not silently promoted to an exact or minimum chemical specification. Explicit inputs such as `MgO ≥ 95%` and `MgO 90` retain their operator and stronger `EXPLICIT_TEXT` evidence.
- The deterministic priority is explicit chemistry → reviewed standard/supplier schema → organization business schema → unresolved input. Only genuinely ambiguous cases, such as a number attached to a multi-constituent composite, ask the user to choose the grade basis.
- Numeric context is classified before grade binding. FEPA grit (`F80`, `P80`), product models (`T60`, `CT800`), alloy grades (`AISI 446`, `6061`), particle size, year, standard number and packaging cannot become purity grades.
- Requests and factor records use the same parser and registry. A source with a missing, different or differently based grade produces a structured Grade Gap; it is never treated as an exact match and no unsupported factor interpolation is performed.
- Grade schema/version, basis component, interpretation, evidence scope, parser rule IDs and rejected numeric roles remain visible in Trace. Grade identity is also part of the normalized business fingerprint.

The Chinese contract and adversarial cases are documented in `docs/CFR_NUMERIC_PURITY_GRADE_V1_ZH.md`.

## Versioned energy-evidence database

Version 0.12.0 uses a separate read-only SQLite evidence database for process-route energy and additional-process resolution. It is deliberately not part of the emission-factor catalogue:

- `energy_quota` stores all three published quota grades, while runtime policy explicitly selects `quota_level=1`;
- `energy_conversion` stores exact values and ranges separately, so an ambiguous range cannot silently become a calculation input;
- `process_parameter` stores independently sourced energy shares, emission factors and route assumptions with exact reference-source scope;
- `enterprise_energy_profile` stores the 89-product workbook as 273 level-specific energy/allocation records, with exact sheet/row/cell and workbook-SHA provenance;
- `enterprise_process_emission` stores level-specific non-energy process emissions, including the electrofused-spinel electrode oxidation term, with original cell, formula, value and review status;
- `quota_modifier_rule` preserves conditional table notes without applying them unless their conditions are separately evidenced;
- every returned `ParameterEvidence` carries the energy-database version/SHA, source standard, table, physical/printed page and evidence status.

“1级” is a quota grade (green benchmark), not a claim that the value is primary/一次能源. Standard quotas are upper-limit engineering proxies, not measured plant consumption and not emission factors.

The supplied standard can be imported locally without committing either the PDF or generated database:

```powershell
pip install -e ".[energy-import]"
python tools/import_refractory_energy_standard.py `
  path\to\T_CHNRISC_0008_2025.pdf `
  path\to\energy_parameters.db `
  --expected-source-sha256 <reviewed-pdf-sha256> `
  --process-parameters-json path\to\reviewed-process-parameters.json `
  --enterprise-energy-workbook path\to\enterprise-energy-89.xlsx `
  --expected-workbook-sha256 <reviewed-workbook-sha256>
```

The workbook is evidence, not an emission-factor catalogue. Formal-safe defaults reject `NEEDS_REVIEW` profiles, cross-material generic carrier parameters and assumed lifecycle-process inclusion. Engineering trial runs may enable these three switches explicitly and must retain the resulting assumptions. Formula `process.replace_energy_and_additional_process/v2` is enabled only when both reference and target routes have exact process-emission evidence. Under the reviewed enterprise-workbook policy, a blank cell is a dataset-default zero only when no carbon/process trigger exists; a conflicting blank or zero requires calculation evidence and cannot close the route.

Connect both formal factor and energy evidence repositories at runtime:

```python
from a1_factor_engine import A1FactorResolutionEngine, SqliteEnergyProcessParameterRepository
from a1_factor_engine.adapters import HttpCatalogFactorRepository

engine = A1FactorResolutionEngine(
    local_retrieval=HttpCatalogFactorRepository(
        endpoint="http://127.0.0.1:5004/api/v2/factors/catalog",
        expected_sha256="<formal-factor-database-sha256>",
    ),
    process_parameters=SqliteEnergyProcessParameterRepository(
        "path/to/energy_parameters.db",
        quota_level=1,
        expected_database_sha256="<energy-database-sha256>",
        # Engineering trial only; formal-safe defaults leave all three False.
        allow_review_profiles=True,
        allow_generic_energy_parameters=True,
        assume_lifecycle_process_inclusion=True,
    ),
)
```

Every derived candidate recomputes `total_emissions_kgco2e` from its new factor and normalized quantity. Locking repeats this invariant check. An otherwise valid `REFERENCE_ONLY` result returns `reference_review_required` and requires a reasoned override. An unresolved process variant returns `process_model_required`; it remains visible only in Trace/exclusions and can never enter Recommendation, approval or locking. Draft, aggregated and pending-review catalogue sources are capped at `REFERENCE_ONLY` unless a reviewed `CatalogDatasetPolicy.production_approval_id` explicitly approves that dataset.

The adapter first matches an exact canonical product, then permits only a unique material/process fallback. Scoped route parameters can additionally bind to an exact factor `source_id`; this prevents a high-alumina ecoinvent proxy whose display name contains “sintered mullite” from receiving the formal sintered-mullite subtraction bundle.

## Mutable trace and database version anchor

Each resolution creates an appendable `ResolutionTrace`; it is an operational explanation record, not an immutable snapshot. It records:

- formal catalogue name, catalogue version, database SHA-256 and endpoint;
- local records found, including source IDs and observed factor values;
- structured candidate gaps and dependency-ordered resolution plans;
- every unit, reference-flow, process or grade transformation, including source IDs, parameter IDs, Formula ID, inputs and output;
- every process-parameter database anchor and the complete evidence records used or found insufficient;
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

Trace stores both the raw-request fingerprint and a normalized business fingerprint. For example, `1 t` and `1000 kg` share the latter. Results before and after a database update can therefore be compared explicitly:

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

The V1 store rejects a duplicate `request_id` and atomically saves the initial Recommendation and Trace. A future repeated-run model should introduce a separate `business_request_id + run_id` contract rather than reusing request IDs.

## Version 0.4 correctness hardening

- Exact Grade anchors are selected before interpolation; all anchors require an explicit compatible series and full Grade Anchor qualification.
- `min_score` remains a solve-first control: lower-scoring candidates are returned at most as `REFERENCE_ONLY`, not silently discarded.
- Unknown factor kind or indicator can be inspected but cannot become Primary.
- HTTP catalogue records preserve original document locator, SHA-256, page, table and row when the API supplies them; the engine never invents missing provenance.
- Supplier source quality depends on verification, audit and documentation evidence rather than the supplier label alone.
- The GitHub Actions workflow runs Python 3.11 lock verification, coverage tests, compile, full Ruff, mypy, FactorBench, package build, and a container health gate.

## Upstream engineering influences

The refinement adopts selected ideas rather than copying any upstream runtime:

- [FAULDIER](https://github.com/ljlazar/fauldier): explicit language/unit/location harmonization and constrained LLM mapping. V1 adds versioned rule evidence and deterministic resolution strength to address model/run variability.
- [Amazon carbon-assessment-with-ml](https://github.com/amazon-science/carbon-assessment-with-ml): bounded candidate retrieval and ranked recommendation from Flamingo/Parakeet. V1 keeps candidate IDs bounded while deterministic formulas and human approval remain authoritative.
- [Brightway2-io](https://github.com/brightway-lca/brightway2-io): sequential linking strategies and preserved unlinked state. V1 exposes the complete strategy ledger and terminates explicitly at unresolved instead of silently relinking.

The external discovery/fetch/extraction/qualification lane now runs after insufficient local evidence and before proxy fallback. It accepts only hash-pinned structured evidence and reuses the same qualification, approval, and locking path; search snippets cannot originate factors.

## Version 0.12 diagnostic and process-accounting contract

- Recommendation separates approvable `candidates` from unapprovable `diagnostic_candidates`. A process-mismatched reference remains visible with provenance, gaps, exclusion reasons and minimum follow-up questions, but cannot be approved or locked.
- Eligible records follow the reviewed project order: refractory consultation draft, ecoinvent 3.10, then ecoinvent 3.12. Applicability gates run before this business preference, and Trace still discloses draft status and the approval policy ID.
- The designated enterprise workbook uses a versioned blank-zero policy. A blank process-emission cell means zero only when no electrode, coke, reductant, oxidation, combustion or decomposition trigger exists.
- Triggered carbon-process emissions can be calculated deterministically from consumable mass, carbon fraction and oxidation fraction using `m × C × oxidation × 44/12`. An incomplete bundle routes to `PROCESS_MODEL_REQUIRED`.
- Purchased electrode/coke production is classified as A1 upstream input; evidenced on-site oxidation, combustion or reaction adds a distinct A3 direct-process contribution.

Version 0.12.1 hardens that contract in three places. Accounting assignments now keep the target product, purchased consumable A1 input and on-site A3 emission event as separate subjects with target-scoped evidence only. Soft `REFERENCE_ONLY` alternatives are returned through `reviewable_candidates` with deterministic review reasons; they cannot enter ordinary approval but remain available to a reasoned `reference_override`. Malformed optional catalogue priority fields fall back to the reviewed inferred source rank and are disclosed through `source_priority_issue` instead of aborting the catalogue.

Version 0.12.2 closes the remaining accounting and governance ambiguities. Chemical entity names such as `氧化铝` cannot trigger A3 without explicit controlled process context. An electrode or coke A1 input can be reported as `IDENTIFIED_NOT_QUANTIFIED` with its missing quantity/upstream-factor inputs, independently from a quantified on-site A3 oxidation event. Reviewable-only results no longer emit a false unresolved message or Trace attempt, and explicit catalogue priority accepts only a real integer from 0 through 1000—floats, booleans and strings fall back per record with a data-quality warning.

Run tests with `pip install -e .[test]` and `pytest`.

## License

This project is open source under the [MIT License](LICENSE). Factor databases, proprietary datasets, and locally generated outputs are not included in this repository.
