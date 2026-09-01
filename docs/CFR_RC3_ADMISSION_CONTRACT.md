# CFR RC3 Structured Energy Admission Contract

Status: FROZEN for the RC3 repair branch

## Purpose

This contract repairs two independently observed rc.2 failures while preserving rc.1 and
rc.2 as immutable NO-GO evidence. It does not change factor values, ranking weights,
approval rules, frozen answers, or the prohibition on same-unit fallback.

## Structured electricity identity

Electricity is a versioned semantic entity (`energy.carrier.electricity`) with reviewed
English and Chinese aliases. A structured electricity record is admitted only when the
existing entity-based declared-product comparison resolves both the request/source name
and declared product to that entity. There is no global substring, token-containment or
exact-link bypass.

Factor kind, explicit subject, source quality, indicator, exact boundary, unit dimension
and evidence gates independently remain mandatory. A different carrier such as gas does
not become compatible merely because both records are energy factors.

## Aluminium ambiguity

`铝金属` is a reviewed alias of elemental aluminium. It does not identify a production
route. When primary and secondary route records are both available, the existing generic
aluminium route-choice contract remains authoritative and returns `MORE_INPUT_NEEDED`.
The one-character Chinese `铝` occurrence rule remains unchanged.

## Status contract

- Ambiguous, resolved material identity with multiple admissible route variants:
  `MORE_INPUT_NEEDED` with `required_choice.field == "route"`.
- No traceable candidate and no actionable identity choice: `SUPPLIER_DATA_REQUIRED`.
- Unit syntax/dimension/catalog failures retain their existing structured reason/status
  mapping.

## Release-safety extension

The following additive rules are also frozen for RC3:

- `energy_factor`, `combustion_factor`, and `transport_factor` are operational lifecycle
  kinds. They must map from structured catalogues, require their matching explicit subject,
  and may reach the same recommendation tiers as lifecycle factors only after every other
  gate passes.
- An explicit request geography must never yield a different explicit geography as a primary
  recommendation. An explicit request year must never yield a source outside a documented
  three-year applicability window as a primary recommendation. Missing source geography/year
  remains visible as reviewable uncertainty, not silently exact evidence.
- Local and external records use the same qualification/admission/observation sinks and
  diagnostics. Conflicting duplicate external `source_id` records fail closed.
- True zero-recall after a complete request remains `SUPPLIER_DATA_REQUIRED`; recalled but
  hard-ineligible evidence returns `UNRESOLVED` with a stable admission reason; missing
  user-selectable discriminators return `MORE_INPUT_NEEDED`.
- Semantic-index/cache identity covers every decision-relevant record field, not only entity
  IDs. Mutating a value, unit, subject, boundary, quality, eligibility, geography, year,
  declared product, aliases or evidence anchor changes the content digest/cache key.
- JSON serialization sorts sets/frozensets deterministically. Replay claims use a stable
  projection that excludes request/trace IDs, timestamps and latency.

## Safety invariants

- No case-ID, source-ID, provider-name, factor-value or benchmark-name branch.
- No automatic approval or lock.
- No cross-boundary, cross-subject or cross-unit admission.
- No lexical or same-unit noise admitted as a substitute for semantic identity.
- rc.1/rc.2 cases, catalogues, expected answers, raw results and reports are not modified.

## Exact write leases

Main-agent lease `CFR-RC3-ADMISSION-001` owns only:

- `src/a1_factor_engine/qualification.py`
- `src/a1_factor_engine/material_registry.py`
- `tests/test_engine.py`
- `docs/CFR_RC3_ADMISSION_CONTRACT.md`

Additional release/version/evidence paths require a later lease after the runtime repair
passes focused tests. Read-only QA agents hold no write lease.

Main-agent lease `CFR-RC3-SAFETY-002` additionally owns:

- `src/a1_factor_engine/adapters.py`
- `src/a1_factor_engine/derived_factor.py`
- `src/a1_factor_engine/engine.py`
- `src/a1_factor_engine/gap_analysis.py`
- `src/a1_factor_engine/graph.py`
- `src/a1_factor_engine/nodes.py`
- `src/a1_factor_engine/semantic_index.py`
- `src/a1_factor_engine/serialization.py`
- focused tests for those modules under `tests/`
