# FactorBench V2 Adjudication: `wrong-unit-53`

Status: **ADJUDICATED FOR V2; V1 IMMUTABLE**

| Field | FactorBench V1 | FactorBench V2 |
|---|---|---|
| Case | `wrong-unit-53` | `wrong-unit-53` |
| Expected status | `supplier_data_required` | `unresolved` |
| Expected reason | historical implicit supplier gap | `UNIT_DIMENSION_MISMATCH` |

The V1 label conflated a unit-system failure with absence of supplier data. CFR's versioned unit
contract requires unit-system failures to remain unresolved with a stable reason code. The
record's `kgCO2e/kWh` is valid syntax but its ENERGY denominator conflicts with the request's
derived MASS target; the frozen Unit Contract therefore requires `UNIT_DIMENSION_MISMATCH`,
not `UNIT_SYNTAX_UNSUPPORTED`. V2 records that precise contract. Historical V1 data and scores
are not rewritten.

This adjudication affects only `wrong-unit-53`. It does not change candidate identity, ordering,
factor values, boundaries, subjects, aliases, or any other benchmark case. The V2 contract first
applies to CFR `0.14.0-rc.1` and later release candidates.

The original case is retained so reviewers can reproduce the historical 8/9 abstention score and
compare it with the V2 contract result. Any later change requires another versioned adjudication.
