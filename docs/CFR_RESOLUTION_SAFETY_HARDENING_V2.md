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

The Portfolio V1 post-fix regression remains visible as raw evidence: 58/60 decisions and 14/54
wrong-or-unlisted returned records when selectable and `REFERENCE_ONLY` records are deliberately
collapsed into one legacy list. The SHA-bound V2 interpretation records 60/60 decisions, 12/12
MORE_INPUT, zero formal wrong/forbidden candidates, and 8/8 exact provisional-option contracts.
It changes no frozen V1 line. Autonomous Evaluation remains a diagnostic gate and its post-fix
output is not represented as an independent or sealed first run.

The steel-fibre runtime correction creates 13 additional raw Autonomous V1 disagreements because
its synthetic oracle treats an unspecified steel-fibre record as directly selectable. Those raw
failures remain visible. A complete case/input/generator-bound V2 adjudication classifies only
those 13 oracle presets as stale, so the effective unresolved count remains 90; the quality gate
continues to fail rather than treating the regression run as release approval.
