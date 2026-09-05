# CFR Unit Field Contract v1

Status: **FROZEN for PR-B review**
Contract ID: `cfr-unit-fields/v1`
Parent baseline: `2f6b52c9effda67a73862b9dca1d3d88487cd8a7`

## Purpose

This contract removes an ambiguity between a factor's application quantity and an auxiliary
mass-normalized quantity. It changes no retrieval, ranking, semantic identity, qualification,
formal factor value, candidate ID, frozen answer or approval decision.

## Authoritative application fields

- `resolved_activity_value` is the quantity used to apply the candidate factor.
- `resolved_activity_unit` is the canonical activity denominator of `factor_unit` and must be
  present with `resolved_activity_value`.
- `activity_dimension` records the controlled activity dimension.
- `total_emissions_kgco2e` is a preview in kilograms of CO2 equivalent, computed as:

  `factor converted to kgCO2e/resolved_activity_unit × resolved_activity_value`.

The activity fields are authoritative for application. A per-tonne factor is multiplied by the
resolved tonnes, a per-gram factor by the resolved grams, and so on. This rule prevents a corrected
kilogram compatibility field from creating a 1,000-fold error.

## Kilogram compatibility field

`resolved_quantity_kg` is retained for backward compatibility. For newly resolved records it has
one meaning only: actual normalized mass in kilograms. Request quantities expressed in grams,
kilograms or tonnes therefore produce the same `resolved_quantity_kg` for the same physical mass.
It is null for energy, transport work, volume, area and count. An evidence-backed reference-flow
conversion may populate it only after that non-mass activity has been deterministically converted
to mass and `activity_dimension` becomes `MASS`. The resulting activity value is then converted
from kilograms to the retained factor denominator before approval and locking.

`resolved_quantity_kg` is auxiliary. It must never be multiplied directly by a factor whose
denominator is not kilograms. The legacy fallback that lacks resolved activity fields is supported
only for mass factors and first converts that factor to `kgCO2e/kg`.

## Impact numerator normalization

Factor inputs using `gCO2e`, `kgCO2e` or `tCO2e` are normalized to `kgCO2e` before a preview total
is stored or validated. The factor value and displayed factor unit remain unchanged unless an
existing explicit factor conversion requested otherwise.

## Integrity and history

All four application fields and the preview total remain part of the candidate content hash. The
corrected semantics therefore apply prospectively to new recommendations, approvals and locks.
Existing locked resolutions, approval bindings, trace bytes, evidence snapshots and historical
exports are immutable and are not migrated, recomputed or rewritten by this change.

At lock time, a resolved activity unit that differs from the factor denominator fails closed.
The stored preview must equal the result recomputed from the aligned activity and normalized impact
numerator. For mass activity, the auxiliary kilograms must also equal the aligned activity converted
to kilograms. Non-finite recomputed totals fail closed. A legacy kilogram fallback is rejected for
non-mass factors.

## API boundary

The production `/api/v1/resolve`, replay and read DTOs continue to omit application internals,
including all resolved activity fields, `resolved_quantity_kg` and the preview total. The explicit
admin/debug surface retains them for controlled diagnosis. This contract does not widen the PR-A
public response allowlist.

## Verification matrix

The regression suite covers every combination of request mass in `g`, `kg` and `t` against factor
denominators `/g`, `/kg` and `/t`; energy, transport-work and volume examples; impact numerators in
`gCO2e`, `kgCO2e` and `tCO2e`; derived factors; fail-closed lock validation; public response
non-disclosure; and immutable lock evidence after later trace annotations.
