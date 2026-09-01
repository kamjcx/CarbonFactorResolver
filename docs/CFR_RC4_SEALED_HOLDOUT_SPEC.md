# CFR RC4 Sealed Holdout Specification

Status: FROZEN after runtime/evaluator commit `b21b8ea48a4ec400372db1621c5d3313f9fe7ca8`

RC4 uses a wholly new public-synthetic dataset after RC3 failed its full frozen case
contract. It must not reuse any RC1/RC2/RC3 case ID, source ID, material/product/alias,
numeric value, catalogue version, database anchor, or expected-answer row. The author must
not read RC3 runtime output and must not run the resolver, API, tests, or evaluator.

## Required shape

- Exactly 48 cases and at least 24 answerable cases.
- At least 10 multilingual exact or reviewed-alias material cases.
- At least 8 ENERGY / TRANSPORT_WORK unit and scale cases, including `energy_factor`,
  `combustion_factor`, and `transport_factor`.
- At least 10 hard safety negatives spanning boundary, subject, unit dimension, indicator,
  declared product, source quality/admission, and forbidden-candidate escape.
- At least 5 `MORE_INPUT_NEEDED` cases spanning aluminium route and missing explicit
  non-material subject.
- At least 5 genuine zero-recall cases.
- Geography/year applicability includes a compatible lower-source-priority record that must
  outrank an incompatible or stale preferred-source record.
- Every evidence locator is under `https://example.invalid/`; all values are synthetic.

## First-run gates

- Full frozen case contract pass rate = 100%.
- Answerable Top-1 >= 90%.
- Retrieval recall before gate >= 95%.
- Abstention correctness >= 90%.
- Boundary, subject, unit-dimension, and forbidden-candidate escapes = 0.
- Deterministic replay = 100%.
- Unhandled HTTP 500 = 0.

The two input files are committed and hashed before the first run. Any runtime, evaluator,
configuration, fixture, or answer change after first execution invalidates RC4 and requires
a new release candidate and a wholly new sealed set.

## File lease

Lease `CFR-RC4-SEALED-AUTHOR-004` permits only creation of:

- `data/sealed/portfolio_rc4_cases.jsonl`
- `data/sealed/portfolio_rc4_catalog.json`
