# FactorBench V1 evaluation methodology

FactorBench is a deterministic JSONL regression suite. Its fixtures are synthetic and public-safe; each run records the dataset hash, Git SHA, package version, registry version/hash, catalogue and semantic-index anchors, energy anchors, and external snapshot hashes.

FactorBench is complemented by two true-data evaluations described in [CFR_TRUE_DATA_ACCEPTANCE.md](CFR_TRUE_DATA_ACCEPTANCE.md): a closed-loop ingestion acceptance and an independently frozen real-query holdout. Results from the ingestion acceptance must not be presented as unknown-query generalization.

The V1 suite contains 57 cases spanning Chinese/English aliases, aluminium alloy and 6061 grade, steel fibre, andalusite/kyanite/sillimanite abstention, fused/sintered process, metal and mineral confusables, route variants, grades, units, invalid indicators/products/boundaries/statuses, local misses, external hits, correct requests for more input, and abstention. Metrics are Entity Accuracy, Recall@1/3/5, MRR, Confusable False Positive Rate, Qualified Candidate Precision, Evidence Completeness, Correct MORE_INPUT Rate, Correct Abstention Rate, External Retrieval Success Rate, and p50/p95 latency.

Safety metrics are gates rather than a license to approve data. A candidate is counted as retrieved only after the normal engine qualification path. Expected hard exclusions must never appear in the returned candidates. Accepted candidates must retain complete source identity, locator, numeric value/unit, indicator, declared product, boundary, and immutable evidence hash.

Exact-stage qualification follows this matrix:

| Request / source | A1 | A2 | A3 | A1-A3 |
|---|---:|---:|---:|---:|
| A1 | PASS | FAIL | FAIL | FAIL |
| A2 | FAIL | PASS | FAIL | FAIL |
| A3 | FAIL | FAIL | PASS | FAIL |
| A1-A3 | FAIL | FAIL | FAIL | PASS |

An aggregated A1-A3 value may be exposed only as `REFERENCE_ONLY` in an explicitly enabled reference workflow; it is never an exact-stage candidate. Subject type and source-quality admission are independent hard qualification dimensions.

Run with:

```bash
cfr benchmark run data/benchmarks/factorbench_v1.jsonl > run.json
cfr benchmark compare baseline.json run.json
```
