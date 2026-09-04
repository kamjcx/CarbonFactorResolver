# Autonomous Evaluation V1 Adjudication

Status: **VERSIONED ADJUDICATION — FROZEN FIRST RUN UNCHANGED**

Machine-enforced record:
[`data/benchmarks/autonomous_evaluation_v1_adjudications.json`](../data/benchmarks/autonomous_evaluation_v1_adjudications.json).
Each entry is bound to the evaluator-contract SHA, semantic case SHA, request-input SHA,
reason, reviewer/authority, adjudication version, and effective software version. A mismatch
fails closed; prose alone cannot exempt a case from a quality gate.

This record resolves six disagreements discovered by Autonomous Evaluation V1. It does not
rewrite the generated cases, their expected answers, the immutable first-run output, or any
historical score.

## Disputed cases

| Case | Frozen expectation | Runtime contract | Decision |
| --- | --- | --- | --- |
| `AUTO-GRID_2024-GEOGRAPHY-X` | unresolved; candidate forbidden | geography difference may be usable with an explicit applicability assumption | benchmark label disagreement |
| `AUTO-GRID_2024-YEAR-X` | unresolved; candidate forbidden | year difference may be usable with an explicit applicability assumption | benchmark label disagreement |
| `AUTO-COAL_MARKET-GEOGRAPHY-X` | unresolved; candidate forbidden | geography difference may be usable with an explicit applicability assumption | benchmark label disagreement |
| `AUTO-COAL_MARKET-YEAR-X` | unresolved; candidate forbidden | year difference may be usable with an explicit applicability assumption | benchmark label disagreement |
| `AUTO-COAL_COMBUSTION-GEOGRAPHY-X` | unresolved; candidate forbidden | geography difference may be usable with an explicit applicability assumption | benchmark label disagreement |
| `AUTO-COAL_COMBUSTION-YEAR-X` | unresolved; candidate forbidden | year difference may be usable with an explicit applicability assumption | benchmark label disagreement |

## Rationale

The published Resolver contract treats geography and year as applicability dimensions rather
than universal identity exclusions. A differing value is disclosed and ranked as
`USABLE_WITH_ASSUMPTIONS`; it requires an explicit human assumption decision before locking.
That behavior is covered by the existing RC3 admission-hardening regression tests. Changing it
to a hard rejection solely to satisfy these six generated labels would silently change the
public contract and invalidate previously reviewed behavior.

The six raw failures therefore remain visible in the unchanged evaluator output. They are
excluded only from the **adjudicated enforceable hard-gate interpretation**, not from raw case
counts. Future evaluator versions must model this contract explicitly and be versioned; V1
answers remain immutable.

## Runtime repairs accepted from the first run

- Ambiguity across multiple otherwise-qualified process, product-form, geography, or year
  values now returns `MORE_INPUT_NEEDED` and keeps alternatives non-selectable.
- Structured HTTP catalogue records without a valid source-document SHA-256 fail closed with
  `SOURCE_DOCUMENT_HASH_REQUIRED`.
- Concurrent duplicate approval attempts are serialized; only the first terminal human
  decision is stored.

These repairs are evaluated as a post-fix regression, not as an independent or sealed first
run.
