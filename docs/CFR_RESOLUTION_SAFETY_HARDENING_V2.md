# CFR Resolution Safety Hardening V2

Status: **STACKED PR — POST-FIX REGRESSION, NOT SEALED EVIDENCE**

This change starts from the Evaluation Gate/Bad Case Audit PR head. It does not rewrite frozen
answers or weaken evaluator gates. It repairs runtime safety defects exposed by that audit.

## Formal contracts

- Explicit geography/year conflicts are hard exclusions. Only a source-side substitution policy
  with an ID, version and explicit dimension may authorize substitution. Reviewer assumption
  acceptance cannot bypass this gate. Unspecified request values remain unknown.
- `A1`, `A2`, `A3` and `A1-A3` require exact boundary-module identity. A missing boundary or
  declared product is visible only as `REFERENCE_ONLY` and cannot be approved or locked.
- Subject and unit conflicts remain hard exclusions. Unresolved numeric grade/specification
  conflicts are diagnostic-only.
- Exact, reviewed Alias and same-entity Related retrieval are qualified as one pool before
  process/form/geography/year ambiguity is decided. Exact affects ranking but cannot hide a
  required choice.
- Reference-flow parameters are revalidated for activity unit, material/product identity,
  packaging, optional specification and conflict state before arithmetic.
- Candidates preserve a generic resolved activity value, unit and dimension. Locking recomputes
  the implied total for mass, energy, transport-work, volume, area and count activities.
- Formal `/api/v1/resolve` rejects `min_score`. The threshold belongs to `DeploymentPolicy`;
  request-side controls exist only through `resolve_debug` and the opt-in debug HTTP route.

## 100/101 adjudication

The historic 100-versus-101 observation was a harness environment defect, not a Resolver
decision. Without the optional API dependency, the harness added an artificial
`AUTO-HTTP-DEPENDENCY` failed row. It now fails before evaluation with a stable operational
error. With the API extra installed, repeated runs have identical result and Bad Case IDs.

The six V1 geography/year `accepted_limitation` records are preserved as history but superseded
by the SHA-bound V2 record. They are classified as real runtime defects and fixed. Frozen V1
inputs and expectations are not edited.

## Verification boundary

The Portfolio post-fix regression has zero forbidden, boundary, subject and unit escapes. Its
remaining precision/MORE_INPUT findings remain visible because this PR does not weaken PR1's
quality thresholds or relabel frozen cases. Autonomous Evaluation remains a diagnostic gate and
its post-fix output is not represented as an independent or sealed first run.
