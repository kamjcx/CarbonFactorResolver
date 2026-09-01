# CFR Unit System Contract v1

Status: **FROZEN**  
Contract ID: `cfr-unit-system/v1`  
Parent baseline: `80b7e864b7b75e43a29702cdae9d941fa072d3bd`

## Scope and invariants

This contract changes unit parsing, dimensional qualification, deterministic scale
conversion and unit-failure reporting only. Retrieval, the Semantic Index, aliases,
ranking weights, frozen benchmark labels, candidate source IDs, factor values, lifecycle
boundaries and factor subject types remain unchanged.

All authoritative scale ratios are `Decimal` values created from strings. Domain and wire
models may continue to expose finite floats at their existing compatibility boundaries.
Every conversion preserves `activity quantity × factor`.

## Unit model

`ActivityDimension` is exactly:

- `MASS`
- `ENERGY`
- `VOLUME`
- `TRANSPORT_WORK`
- `COUNT`

The canonical impact unit is `kgCO2e`. Controlled spellings include `kgCO2e`,
`kg CO2e`, `kgCO2eq` and `kg CO2-eq`, case-insensitively. Existing `gCO2e` support is
retained as a scaled compatibility input. Original text is retained for Trace.

`ActivityUnitSpec` contains the canonical unit, dimension, Decimal ratio to the dimension
base and whether a conversion needs external evidence. `ParsedFactorUnit` contains the
impact unit and activity denominator explicitly. Compatibility properties retain the old
`numerator`, `denominator_mass` and reference-product qualifier API.

`UnitConversionResult` records raw and canonical source/target units, conversion direction,
Decimal multiplier, Formula ID, evidence requirement and reason code.

## Registry and bases

| Dimension | Base | Controlled units and ratio to base |
|---|---|---|
| MASS | kg | g=`0.001`, kg=`1`, t/tonne=`1000`, lb=`0.45359237` |
| ENERGY | kWh | kWh=`1`, MWh=`1000`, MJ=`1/3.6`, GJ=`1000/3.6` |
| VOLUME | m3 | m3=`1`, L=`0.001`, Nm3=`1` with evidence gate |
| TRANSPORT_WORK | tkm | tkm=`1`, kgkm=`0.001` |
| COUNT | item | item/count/piece/pcs=`1` |

`Nm3` is in `VOLUME` but is not assumed equivalent to `m3`. Any `m3 ↔ Nm3`
conversion returns `UNIT_CONVERSION_EVIDENCE_REQUIRED` unless a controlled, versioned
evidence record supplies the direction and multiplier. Identity conversions do not need
evidence.

## Factor direction

For factors, the denominator direction determines the multiplier:

- `kgCO2e/t → kgCO2e/kg`: divide by `1000`.
- `kgCO2e/MWh → kgCO2e/kWh`: divide by `1000`.
- `kgCO2e/tkm → kgCO2e/kgkm`: divide by `1000`.

Activity quantity conversion uses the inverse direction so emissions remain invariant.

## Default target unit

When `target_factor_unit` is omitted, the effective target is derived from the canonical
request activity unit: `kgCO2e/<activity unit>`. An explicitly supplied target is never
silently replaced. The effective target and derivation rule are recorded in Trace.

## Stable reason codes and terminal mapping

| Reason code | Meaning | Status / Follow-up |
|---|---|---|
| `UNIT_SYNTAX_UNSUPPORTED` | Request activity or target unit cannot be parsed | `UNRESOLVED / UNRESOLVED` |
| `CATALOG_FACTOR_UNIT_INVALID` | A catalogue record has an invalid factor unit | `UNRESOLVED / DATA_GOVERNANCE` if no alternative is usable |
| `UNIT_DIMENSION_MISMATCH` | Parsed activity dimensions differ | `UNRESOLVED / UNRESOLVED` if no alternative is usable |
| `UNIT_CONVERSION_EVIDENCE_REQUIRED` | Same dimension, but controlled conversion evidence is missing | `MORE_INPUT_NEEDED / MORE_INPUT` |

`SUPPLIER_DATA_REQUIRED` is reserved for a genuine absence of traceable factor/source data.
If another qualified candidate is usable, record-level unit findings stay diagnostic and do
not replace `RECOMMENDATION_READY`.

The same code must appear in `QualificationDiagnostic`, `CandidateAdmission`, exclusions,
Top-K Trace, `Recommendation.reason_codes` and API serialization. Human detail messages may
be additive but are never the machine contract.

## Compatibility and exclusions

- `convert_mass()` and `convert_factor()` retain their public signatures and float return.
- Existing kg/g/t behavior and product qualifiers remain supported.
- No count-to-mass, cross-dimension or m3-to-Nm3 conversion is inferred.
- No numeric value may originate from an LLM or an unversioned evidence mapping.
- FIN-05 is outside this contract and remains `MORE_INPUT_NEEDED` until adjudicated.

