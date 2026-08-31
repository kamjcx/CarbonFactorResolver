# CFR Energy Evidence Database V1

## Purpose

The energy database supplies auditable numeric inputs to the existing Process Variant Router. It does not replace the formal emission-factor catalogue and never creates a factor on its own.

The implemented data path is:

```text
formal factor candidate
  + exact Level-1 reference quota
  + exact Level-1 target quota
  + complete energy shares
  + exact conversion coefficients
  + sourced energy emission factors
  + exact additional process emissions when present
  + explicit process-inclusion evidence
→ process.replace_energy_components/v1
  or process.replace_energy_and_additional_process/v2
→ PROCESS_ADJUSTED candidate
```

If any required input is absent, ambiguous or out of scope, the candidate remains `UNADJUSTED_PROCESS_PROXY`.

## Database boundary

The generated SQLite file is local operational data and is ignored by Git. The source standard PDF is also ignored. The repository contains only:

- the schema/builder and read-only adapter;
- a source-hash-checked importer;
- test fixtures and deterministic regression expectations;
- integration documentation.

## Schema

### `energy_quota`

One row represents one product, quota grade and standard source row. Important fields are:

- exact `canonical_product`;
- `head_material` and `production_process` fallback keys;
- `quota_level` and `value_kgce_per_t`;
- standard/table/physical page/printed page;
- source PDF SHA-256, applicability and note IDs.

Runtime first matches `canonical_product`. A head-material/process match is accepted only when unique.

### `energy_conversion`

Stores `value_min` and `value_max`. Only an exact value (`min == max`) with a Process Router parameter name can be emitted automatically. The natural-gas range in Annex A therefore remains reference evidence and cannot silently replace an exact measured or reviewed coefficient.

### `process_parameter`

Stores route-specific parameters such as energy shares and emission factors. Scope contains:

- reference head material and process;
- target head material and process;
- optional exact factor `reference_source_id`;
- source type, provider, locator, citation and quality note.

### `enterprise_energy_profile`

Stores the first worksheet of the reviewed 89-product enterprise workbook as one row per product-route and quota level. The current import contains 91 product-route rows across 89 sequence IDs and three levels, for 273 records total. Every record retains:

- exact worksheet, row, energy cell, electricity-share cell and formula cell;
- workbook SHA-256, source citation, provider and quality note;
- total energy, electricity share, remainder carrier and remainder share;
- allocation status, runtime-eligibility flag and formal-quota comparison metadata.

The runtime adapter selects the configured quota level (Level 1 by default) and requires an exact canonical product/route match. Formal-safe defaults reject review-only profiles, generic cross-material carrier parameters and assumed lifecycle-process inclusion. Engineering trial runs may enable them explicitly; Trace then records `calculation_with_assumption=true`, review notes, workbook SHA and cells. Standard-coal rows, unresolved remainder carriers and ambiguous duplicate keys remain non-calculable.

Carrier parameter precedence is exact route-scoped evidence, then one unique database-wide carrier value, then an exact formal conversion. Generic fallback is allowed only when all active database observations for the parameter agree on value and unit; its original parameter IDs and the cross-route assumption are preserved. When an exact profile pair is used with a lifecycle reference, the approved policy emits a separate non-numeric inclusion witness so the subtraction assumption is explicit in the transformation lineage.

An exact eligible enterprise profile supersedes older numeric route shares or total-energy values with the same semantic name. A separately reviewed scoped assertion that the reference factor includes the replaced process is preserved as a non-numeric inclusion witness; it does not override enterprise values.

### `enterprise_process_emission`

Stores level-specific non-energy process emissions only for product rows with an explicitly resolved production process. Each row retains canonical product, route, quota level, emission kind, `kgCO2e/t` source value, worksheet/cell/formula, remark, review status and workbook SHA. Runtime converts the selected exact record deterministically to `kgCO2e/kg`; it does not infer process emissions from names.

For electrofused spinel, cells `P61/Q61/R61` contain `33 kgCO2/t` and the formula `9 × 44 / 12`, corresponding to direct oxidation of 9 kg carbon electrode per tonne of product. The sintered route cells `P64/Q64/R64` are explicit zeros. Because the source rows remain marked for review, Trace retains `calculation_with_assumption=true`.

V2 replacement requires evidence on both sides. Numeric zero is valid evidence; an absent database row is not zero. For the designated enterprise workbook only, importer policy `enterprise-energy-89.blank-zero-unless-process-trigger/v1` turns a blank into a dataset-default zero when no process trigger is present. Electrode, coke, graphite, reductant, carbon, oxidation, combustion, decomposition or `44/12` evidence overrides that default: a blank/zero is marked `requires_process_emission_calculation` and cannot close the route until the process amount is calculated. If one side remains unresolved, the Router records an unadjusted diagnostic candidate and returns `process_model_required`; the diagnostic never enters approval. The current 63 imported observations are numeric cells (54 positive, 9 numeric zeros), so this policy change does not alter the current database contents or SHA until a controlled rebuild.

### `quota_modifier_rule`

Stores conditional notes such as crushing-process additions. V1 preserves these rules but does not apply them automatically because the triggering facts must first be supplied as structured evidence.

## Mullite route

For `烧结莫来石 → 电熔莫来石`, the formal standard contributes Level-1 quotas of 365 and 165 kgce/t. The enterprise workbook instead supplies exact Level-1 profiles:

- reference `烧结莫来石`: 94 kgce/t, electricity 0.24, natural gas 0.76, workbook row 32;
- target `电熔莫来石`: 162 kgce/t, electricity 1.00, natural gas 0.00, workbook row 29;
- workbook SHA-256: `8aeee0243763d3432f9921ad5032c5d954c070188608f281202baeaea8631aa2`.

The differences from the formal quotas are retained in metadata rather than silently reconciled. The workbook does not supply the natural-gas conversion coefficient, selected energy emission factors or proof that a formal lifecycle factor includes the removed process; these remain separately sourced and scoped process evidence.

Against formal-catalogue SHA `799bff31...34e06`, the complete reviewed bundle reconstructs the formal draft sintered-mullite factor as:

```text
reference process energy = 0.270343966 kgCO2e/kg
common upstream          = 3.161011034 kgCO2e/kg
target process energy    = 0.761492270 kgCO2e/kg
target electrode process = 0.018000000 kgCO2e/kg
derived factor           = 3.940503304 kgCO2e/kg
```

The bundle is bound to the formal draft-standard sintered-mullite source ID. The ecoinvent high-alumina refractory production proxy receives only generic quota evidence and remains unadjusted.

## Spinel route validation

The live validation request `电熔尖晶石, 1 kg, CN, 2025` uses the formal sintered-spinel lifecycle factor and exact enterprise route evidence:

- the semantic registry resolves `head_material=spinel` and `production_process=electrofused`;
- the formal catalogue recalls both sintered/electrofused emission-limit observations and the lifecycle factor for sintered spinel;
- emission-limit observations are rejected as lifecycle-factor candidates;
- the Level-1 quota evidence is found for sintered magnesia-alumina spinel (`375 kgce/t`) and electrofused magnesia-alumina spinel (`185 kgce/t`);
- the electricity equivalent-value coefficient (`0.1229 kgce/kWh`) is retained as conversion evidence;
- exact enterprise profiles provide closed Level-1 shares: sintered electricity/natural gas `0.021/0.979`, electrofused electricity/natural gas `1.0/0.0`;
- the database-priority policy supplies Trace-visible carrier fallback and process-inclusion assumptions;
- exact process-emission records provide sintered `0` and electrofused electrode oxidation `33 kgCO2/t`;
- Formula `process.replace_energy_and_additional_process/v2` returns `4.623698092 kgCO2e/kg`.

The Level-1 decomposition is:

```text
reference lifecycle factor          = 4.602431000
- reference electricity             = 0.037016985
- reference natural gas             = 0.844321293
- reference additional process      = 0.000000000
+ target electricity                = 0.869605370
+ target additional process         = 0.033000000
= derived electrofused factor       = 4.623698092 kgCO2e/kg
```

Levels 2 and 3 use their own exact cells and return `4.563588974` and `4.520099655 kgCO2e/kg`. These remain assumption-bearing scenario results; the formal candidate is still capped at `REFERENCE_ONLY` by missing formal-catalogue metadata and Grade qualification limitations.

The two quota values must not be used as a direct factor ratio. In particular, the engine must not derive:

```text
electrofused factor = sintered lifecycle factor × 185 / 375
```

That expression would implicitly assume that the whole lifecycle factor is route energy, that both routes have the same energy carrier mix, and that all common upstream components scale with quota energy. None of these assumptions is established by the quota standard.

### Parameter completion contract

Future reviewed evidence can be added through `process_parameter` or the enterprise process-emission import without changing the Graph. A complete reconstruction bundle must provide:

- `reference_electricity_share` and every other reference-route energy share;
- `target_electricity_share` and every other target-route energy share, including explicit zero shares where applicable;
- exact selected conversion coefficients for each energy carrier;
- geography/year/boundary-compatible energy emission factors;
- explicit evidence that the selected sintered lifecycle factor includes the process energy being removed;
- exact reference and target additional-process records when the route has non-energy process emissions;
- scope binding to the reference factor `source_id`, reference/target material and reference/target process.

Reference and target shares must each close to `1.0`. Partial shares, an ambiguous coefficient range, unsupported cross-material transfer (for example reusing mullite shares for spinel), or an unscoped process-inclusion claim cannot activate deterministic rebuilding. After the bundle is reviewed and published as a new energy-database version, the same request can be rerun and compared by normalized request fingerprint and both database anchors.

## Trace contract

Each process event records:

- selected mode and candidate ID;
- complete `ParameterEvidence` objects;
- factor source scope;
- energy database name, dataset version, schema version, path and SHA-256;
- standard/table/page/source-PDF SHA;
- formula inputs, common upstream, output and assumptions.

This supports comparison when either the formal factor catalogue or energy database changes.

## Current local database anchor

- dataset version: `t-chnrisc-0008-2025+enterprise-energy-89/v4`;
- schema version: `5`;
- local path: `D:\carbon-data\energy_parameters.db`;
- database SHA-256: `0d47d6eac30e6de3ef110638506ae370aa68d87c57811b1f35a9060cef1d005a`;
- records: 309 quotas, 31 conversions, 14 modifier rules, 273 enterprise profiles and 63 process-emission observations;
- runtime-eligible enterprise records: 193.

The 193 count is the pre-reviewed subset. Exact `NEEDS_REVIEW` natural-gas/all-electric profiles are additionally usable only through the assumption-bearing database-priority policy; the source quality flag is not rewritten.

The source workbook and generated database are excluded from Git. The local anchor changes whenever the database is rebuilt, and Trace records the exact anchor used.
