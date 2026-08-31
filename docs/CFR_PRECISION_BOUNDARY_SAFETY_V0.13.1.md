# CFR v0.13.1 Precision & Boundary Safety Hardening

## Decision

The v0.13.1 code gate is **PASS** for precision and boundary hardening. This decision does not approve any extracted factor and does not authorize writing true-data outputs into a formal catalogue.

## Implemented controls

- Exact A1/A2/A3/A1-A3 qualification uses a 4×4 matrix. Stage totals do not qualify for an exact stage.
- `FactorSubjectType` is a hard qualification dimension: raw material, finished product, energy, transport, process, waste, and unknown.
- `SourceQualityStatus` and `admission_eligible` are hard, fail-closed admission dimensions for catalogue and external records.
- Related semantic retrieval cannot bypass an explicit product entity.
- Report pairing is strict and duplicate IDs fail closed.
- Numeric evidence retains raw Decimal text and display precision.
- PDF cross-checks bind page, table, lifecycle-stage row, Carbon Footprint column, and exact value.
- Error-level source findings remain available for diagnosis but are rejected from admission.
- API tests run with API dependencies in CI; core modules no longer rely on the previous mypy ignore blocks.

## Evaluation separation

`TrueDataIngestionAcceptance` is a closed-loop test of extraction, evidence, admission, and retrieval consistency. It is not described as a blind or unknown-query benchmark.

`RealQueryHoldoutBenchmark` is independently frozen in `data/benchmarks/real_query_holdout_v1.jsonl`. It contains 32 human-authored business queries: 8 positive retrievals, 4 `MORE_INPUT` cases, and 20 abstention negatives.

## Verified local results

| Gate | Result |
|---|---:|
| Package tests | 186 passed |
| Package branch coverage | 85.59% |
| True-data tool tests | 13 passed |
| True-data tool branch coverage | 43.24% |
| Ruff | PASS |
| mypy | PASS |
| Ingestion Recall@5 / Top-1 | 100% / 100% |
| Ingestion wrong-candidate rate | 0% |
| Holdout Recall@5 / Top-1 | 100% / 100% |
| Holdout wrong-candidate rate | 0% |
| Holdout correct abstention | 100% (20/20) |
| Holdout `MORE_INPUT` positive recall | 100% (4/4) |
| Holdout `MORE_INPUT` negative specificity | 100% (28/28) |

The true-data run extracted 72 factors from 18 DOCX/PDF pairs. Report 11 produced one error-level net-emissions mismatch; all four of its factor records are retained as `REJECTED` with `admission_eligible=false`.

## Remaining boundary

- Formal catalogue admission remains a separate human-governed workflow.
- Generated true-data outputs are ignored and must not be committed to the public repository.
- `carbon-report` integration should consume v0.13.1 only after the remote CI and PR checks are green.
