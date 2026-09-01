# FactorBench V3 Admission Adjudication

Status: **ADJUDICATED FOR V3; V1 AND V2 IMMUTABLE**

FactorBench V3 retains every V2 query, fixture, candidate ID and factor value. It changes
only the expected terminal contract for three cases where a record is recalled and then
hard-rejected by deterministic admission gates.

| Case | V2 expected | V3 expected | Stable reason |
|---|---|---|---|
| `wrong-indicator-54` | `supplier_data_required` | `unresolved` | `ADMISSION_REJECTED` |
| `wrong-product-55` | `supplier_data_required` | `unresolved` | `ADMISSION_REJECTED` |
| `wrong-boundary-56` | `supplier_data_required` | `unresolved` | `ADMISSION_REJECTED` |

`SUPPLIER_DATA_REQUIRED` means the completed structured request produced no traceable
record. These three cases do have a traceable record; it is unusable because the indicator,
declared product, or boundary is incompatible. Returning `UNRESOLVED` preserves that data
governance fact and prevents a rejected catalogue record from being mistaken for a simple
coverage gap.

Historical V1/V2 files and reported scores are not rewritten. `wrong-unit-53` retains the
V2 unit adjudication. V3 first applies to RC3 and later versions. This adjudication changes
no retrieval, ranking, factor value, source identity, approval, or lock behavior.
