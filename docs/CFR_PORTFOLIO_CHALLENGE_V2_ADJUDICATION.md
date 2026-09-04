# CFR Portfolio Challenge V2 Adjudication

Status: **POST-FIX REGRESSION CONTRACT — NOT INDEPENDENT OR SEALED EVIDENCE**

## Purpose

Portfolio Challenge V1 remains immutable. Its single `observed_ids` field predates the Resolver's
distinction between selectable recommendations and non-selectable `REFERENCE_ONLY` discovery
evidence. Consequently V1 counts valid ambiguity clues as wrong formal candidates and contains two
decision labels that conflict with the later fail-closed safety contract.

The V2 overlay does not edit V1. Every entry is bound to the complete challenge SHA, case SHA,
input SHA, original decision, reason, adjudication version and effective software version. Raw V1
rows and metrics remain in every output.

## Adjudicated contracts

- `FIN-05`: `钢纤维制品` requires `steel_fiber_type`; the product record is reference-only.
- `CNF-01`: generic metallic aluminium requires a primary/secondary route choice; generic,
  primary and secondary records are non-selectable route evidence.
- `MI-01` through `MI-03`: V1 already expects MORE_INPUT; V2 supplies the exact allowed aluminium
  reference set and route choice that V1 cannot represent.
- `MI-04` through `MI-06`: English and Chinese steel-fibre inputs require subtype; generic steel
  is reference-only and the three disclosed subtype options must match the frozen V2 contract.

## Raw and effective metrics

The evaluator emits both interpretations:

- `runs.full_cfr.metrics` and `raw_quality_gate`: unchanged V1 scoring over the legacy combined
  candidate list;
- `runs.full_cfr.effective_metrics` and `quality_gate`: V2 scoring, where only fully adjudicated
  cases separate formal candidates from reference/provisional evidence;
- `provisional_option_validity`, `reference_only_set_validity`, `required_choice_validity`, and
  `formal_candidate_escape_count`: explicit protection against hiding or silently ignoring clues.

An unbound, duplicate, stale, incomplete, or unknown adjudication fails before evaluation. V2 does
not approve any factor, change any catalogue value, or convert a reference-only record into a
selectable candidate.
