# OFR Energy Evidence Database V1

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
  + explicit process-inclusion evidence
→ process.replace_energy_components/v1
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

### `quota_modifier_rule`

Stores conditional notes such as crushing-process additions. V1 preserves these rules but does not apply them automatically because the triggering facts must first be supplied as structured evidence.

## Mullite route

For `烧结莫来石 → 电熔莫来石`, the standard contributes only:

- Level-1 reference quota: 365 kgce/t;
- Level-1 target quota: 165 kgce/t;
- electricity equivalent-value coefficient: 0.1229 kgce/kWh.

The standard does not publish the 76%/24% reference energy split, the 100% target electricity split, a unique 1.2143 natural-gas coefficient, or energy emission factors. These stay in separately sourced process-parameter records.

With the complete reviewed bundle, the deterministic result is:

```text
reference process energy = 1.505402201 tCO2e/t
common upstream          = 1.925952799 tCO2e/t
target process energy    = 0.775593979 tCO2e/t
derived factor           = 2.701546778 tCO2e/t
```

The bundle is bound to the formal draft-standard sintered-mullite source ID. The ecoinvent high-alumina refractory production proxy receives only generic quota evidence and remains unadjusted.

## Spinel route validation

The live validation request `电熔尖晶石, 1 t, CN, 2024` proves the intended fail-safe behavior of the Process Variant Router:

- the semantic registry resolves `head_material=spinel` and `production_process=electrofused`;
- the formal catalogue recalls both sintered/electrofused emission-limit observations and the lifecycle factor for sintered spinel;
- emission-limit observations are rejected as lifecycle-factor candidates;
- the Level-1 quota evidence is found for sintered magnesia-alumina spinel (`375 kgce/t`) and electrofused magnesia-alumina spinel (`185 kgce/t`);
- the electricity equivalent-value coefficient (`0.1229 kgce/kWh`) is retained as conversion evidence;
- because the route energy shares, selected energy emission factors and explicit process-inclusion evidence are incomplete, the lifecycle candidate remains `UNADJUSTED_PROCESS_PROXY / REFERENCE_ONLY` at its original value.

The two quota values must not be used as a direct factor ratio. In particular, the engine must not derive:

```text
electrofused factor = sintered lifecycle factor × 185 / 375
```

That expression would implicitly assume that the whole lifecycle factor is route energy, that both routes have the same energy carrier mix, and that all common upstream components scale with quota energy. None of these assumptions is established by the quota standard.

### Deferred parameter completion contract

Future reviewed evidence can be added through `process_parameter` without changing the Graph or numeric formula. A complete spinel reconstruction bundle must provide:

- `reference_electricity_share` and every other reference-route energy share;
- `target_electricity_share` and every other target-route energy share, including explicit zero shares where applicable;
- exact selected conversion coefficients for each energy carrier;
- geography/year/boundary-compatible energy emission factors;
- explicit evidence that the selected sintered lifecycle factor includes the process energy being removed;
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
