# CFR RC3 Sealed Holdout Specification

Status: FROZEN after runtime/config commit `5b085f4f33efadef706fe5b51c74bad3030d68fb`

The RC3 sealed set is a wholly new public-synthetic dataset. It must not reuse rc.1/rc.2
case IDs, source IDs, product names, numeric values, catalogue version, database anchor,
or expected-answer rows. The author may read frozen contracts and schemas but must not run
the resolver, tests, API, or evaluator while authoring.

## Required shape

- 48 cases total.
- At least 20 answerable cases.
- 8 or more exact/alias multilingual material cases.
- 6 or more ENERGY / TRANSPORT_WORK unit and scale cases.
- At least one each for `energy_factor`, `combustion_factor`, and `transport_factor`.
- At least 8 hard safety negatives spanning boundary, subject, unit dimension,
  indicator, declared product, source quality/admission, and forbidden candidate escape.
- At least 4 `MORE_INPUT_NEEDED` cases spanning aluminium route and missing explicit
  non-material subject.
- At least 4 true zero-recall cases.
- Geography/year applicability must include a lower-priority compatible record outranking
  a preferred incompatible/stale record.
- All evidence locators use `https://example.invalid/`; all data are clearly synthetic.

## First-run gates

- Answerable Top-1 >= 90%.
- Retrieval recall before gate >= 95%.
- Abstention correctness >= 90%.
- Boundary, subject, unit-dimension and forbidden-candidate escapes = 0.
- Deterministic replay = 100%.
- Unhandled HTTP 500 = 0.

The two input files are committed and hashed before the first run. Any runtime/config change
after that first run invalidates RC3 and requires RC4 plus a wholly new set.

## File lease

Lease `CFR-RC3-SEALED-AUTHOR-003` belongs only to `/root/rc3_holdout_author` and permits
creation of exactly these absent files:

- `data/sealed/portfolio_rc3_cases.jsonl`
- `data/sealed/portfolio_rc3_catalog.json`

The author must not modify any other file or Git state and must return file hashes and a
static schema/count audit without executing CFR.
