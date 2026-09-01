# CFR RC6 Sealed Holdout Specification

Status: FROZEN after runtime/evaluator commit `1c8be4ca3ef0a1402a0ef343a024972e7a0e6320`

RC6 is a wholly new public-synthetic sealed set. It must not reuse any RC1–RC5 case/source
ID, material/product/alias, numeric value, catalogue/database anchor, or answer row. The
author must not read prior sealed outputs or execute CFR, API, tests, or evaluator.

Preflight requirements are release blockers before the input commit:

- `database.sha256` is exactly 64 lowercase hexadecimal characters.
- Every source-document SHA is exactly 64 lowercase hexadecimal characters.
- JSON/JSONL schemas, request fields, IDs, references, and expected terminal/reason contracts
  pass static validation.
- Exact primary names expect `recommendation_ready`; reviewed aliases expect
  `reference_review_required`; missing operational subject expects `more_input_needed` with
  no reason code; genuine hard rejection expects `unresolved` with its stable reason.

## Required set and gates

- Exactly 48 cases; at least 24 answerable.
- At least 10 multilingual exact/alias cases and at least 8 energy/transport cases.
- At least 10 hard safety negatives across all qualification dimensions.
- At least 5 `MORE_INPUT_NEEDED` and 5 genuine zero-recall cases.
- Geography/year applicability and source-priority inversion are covered.
- All evidence locators use `https://example.invalid/` and all data are synthetic.
- Full case contract = 100%; Top-1 >= 90%; retrieval recall >= 95%; abstention >= 90%.
- Boundary/subject/unit/forbidden escapes = 0; replay = 100%; HTTP 500 = 0.

Inputs are committed and hashed before first execution. Any post-run runtime/evaluator/
configuration/fixture/answer change requires another RC and another wholly new set.

Lease `CFR-RC6-SEALED-AUTHOR-006` permits only:

- `data/sealed/portfolio_rc6_cases.jsonl`
- `data/sealed/portfolio_rc6_catalog.json`
