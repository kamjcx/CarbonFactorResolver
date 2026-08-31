# True-data acceptance workflow

`tools/true_data_acceptance.py` builds an isolated, read-only acceptance run
from paired two-page DOCX/PDF product-carbon-footprint reports.

The workflow:

1. pairs reports by the leading two-digit report identifier;
2. freezes the source paths, sizes, and SHA-256 hashes;
3. extracts A1, A2, A3, and A1-A3 total product-footprint values;
4. cross-checks every value against PDF text;
5. emits one CSV test table per extracted factor;
6. freezes a JSONL blind-test manifest before running the resolver;
7. runs CarbonFactorResolver against an isolated catalogue snapshot; and
8. records Recall@5, wrong-candidate rate, correct abstention,
   MORE_INPUT agreement, evidence completeness, traces, and source-quality
   findings.

The tool does not write to a formal factor catalogue or an approval store. Its
output directory should remain ignored because reports and extracted values may
be confidential.

## Dependencies

Install the existing optional import group, which includes `pdfplumber` and
`python-docx`:

```powershell
uv sync --extra energy-import
```

## Run

```powershell
uv run --extra energy-import python tools/true_data_acceptance.py `
  <SOURCE_DIR> <OUTPUT_DIR>
```

The source directory must contain exactly 18 matching `.docx`/`.pdf` pairs.
The command fails closed when files are unpaired, lifecycle rows are missing,
or the expected 72 factors cannot be extracted.

Important output files:

- `source_manifest.json`: immutable source inventory;
- `extracted_factors.json`: complete factor records and evidence coordinates;
- `factor_test_tables/*.csv`: one independent table per factor;
- `blind_test_manifest.jsonl` and `.sha256`: frozen expected answers;
- `isolated_catalog_snapshot.json`: non-formal run-only catalogue;
- `cfr_results.json`: case results and complete resolver traces;
- `metrics.json`: aggregate acceptance metrics;
- `source_quality_findings.json`: arithmetic and cross-format findings; and
- `run_manifest.json`: run anchors and explicit no-write assertions.

Do not commit generated true-data outputs to the public repository. Only the
generic runner, tests, dependency declaration, and this procedure are intended
for version control.
