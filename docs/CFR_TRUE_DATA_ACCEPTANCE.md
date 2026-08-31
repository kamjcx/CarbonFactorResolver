# True-data acceptance workflow

`tools/true_data_acceptance.py` performs two deliberately separate read-only evaluations from paired two-page DOCX/PDF product-carbon-footprint reports:

1. **TrueDataIngestionAcceptance** validates report extraction, evidence coordinates, quality admission, and closed-loop retrieval against an isolated catalogue built from the same extracted records.
2. **RealQueryHoldoutBenchmark** runs a separately frozen set of human-authored business queries. It is not generated from catalogue names at runtime and is the only part used to claim query-level precision, abstention, and `MORE_INPUT` behavior.

Neither evaluation writes to a formal factor catalogue or approval store.

## Safety model

- Files must match `NN--name.docx` / `NN--name.pdf`; duplicate or unpaired IDs fail closed.
- DOCX and PDF hashes are frozen and verified again after the run.
- PDF verification binds page, table, lifecycle-stage row, Carbon Footprint column, and exact decimal value.
- `FOOTPRINT_STAGE_SUM_MISMATCH`, `NET_EMISSIONS_SUM_MISMATCH`, `PAGE_TOTAL_MISMATCH`, and cross-format failures make the report records ineligible for admission.
- The A1/A2/A3/A1-A3 boundary matrix is exact. Aggregated values never qualify as exact-stage factors.
- `FactorSubjectType` prevents raw-material requests from qualifying finished-product factors.
- Output manifests contain evidence IDs and hashes, not absolute source paths.

## Run

```powershell
uv run --isolated --all-extras python tools/true_data_acceptance.py `
  <SOURCE_DIR> <NEW_OUTPUT_DIR> `
  --expected-pairs 18 `
  --holdout-manifest data/benchmarks/real_query_holdout_v1.jsonl
```

The output directory must be new or empty and must not overlap the source directory.

Important output files:

- `source_manifest.json`: redacted immutable source inventory;
- `extracted_factors.json`: factor records with evidence coordinates and quality state;
- `factor_test_tables/*.csv`: one test table per extracted factor;
- `ingestion_acceptance_manifest.jsonl` and `.sha256`: frozen closed-loop acceptance cases;
- `isolated_catalog_snapshot.json`: non-formal run-only catalogue;
- `cfr_results.json` and `metrics.json`: closed-loop results and metrics;
- `real_query_holdout_results.json` and `real_query_holdout_metrics.json`: independent holdout results;
- `source_quality_findings.json`: arithmetic and cross-format findings;
- `release_gate.json`: explicit pass/fail checks;
- `真实数据验收报告.md`: generated human-readable report; and
- `run_manifest.json`: run anchors and explicit no-write assertions.

The release gate requires zero closed-loop wrong candidates, Holdout wrong-candidate rate at most 5%, at least 95% correct abstention with at least 20 negative cases, at least 95% positive `MORE_INPUT` recall and negative specificity, complete evidence metadata, and no resolver errors.

Do not commit generated true-data outputs. Only the generic runner, tests, static public-safe holdout, dependency declaration, and this procedure are versioned.
