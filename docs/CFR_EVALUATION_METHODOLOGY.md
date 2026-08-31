# FactorBench V1 evaluation methodology

FactorBench is a deterministic JSONL regression suite. Its fixtures are synthetic and public-safe; each run records the dataset hash, Git SHA, package version, registry version/hash, catalogue and semantic-index anchors, energy anchors, and external snapshot hashes.

The V1 suite contains 57 cases spanning Chinese/English aliases, aluminium alloy and 6061 grade, steel fibre, andalusite/kyanite/sillimanite abstention, fused/sintered process, metal and mineral confusables, route variants, grades, units, invalid indicators/products/boundaries/statuses, local misses, external hits, correct requests for more input, and abstention. Metrics are Entity Accuracy, Recall@1/3/5, MRR, Confusable False Positive Rate, Qualified Candidate Precision, Evidence Completeness, Correct MORE_INPUT Rate, Correct Abstention Rate, External Retrieval Success Rate, and p50/p95 latency.

Safety metrics are gates rather than a license to approve data. A candidate is counted as retrieved only after the normal engine qualification path. Expected hard exclusions must never appear in the returned candidates. Accepted candidates must retain complete source identity, locator, numeric value/unit, indicator, declared product, boundary, and immutable evidence hash.

Run with:

```bash
cfr benchmark run data/benchmarks/factorbench_v1.jsonl > run.json
cfr benchmark compare baseline.json run.json
```
