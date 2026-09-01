# CFR RC5 Sealed Holdout Specification

Status: FROZEN after runtime/evaluator commit `5f3d656c34a46c67d4ac737c8b312034568cb493`

RC5 is a wholly new public-synthetic sealed set. It must not reuse any RC1–RC4 case/source
ID, material/product/alias, numeric value, catalogue/database anchor, or expected-answer row.
The author must not read prior sealed outputs or run the resolver, API, tests, or evaluator.

The expected contract must distinguish result tiers explicitly:

- Exact primary-name matches with complete qualification may be `recommendation_ready`.
- Reviewed/catalogue aliases are `reference_review_required`; they remain selectable only
  through explicit review and must not be labelled primary recommendations.
- Applicability comparisons reached through aliases are also review-only; ranking of the
  compatible/current record is still asserted.
- Missing explicit ENERGY/TRANSPORT subject returns `more_input_needed` with no
  `ADMISSION_REJECTED`; genuinely recalled and hard-ineligible records return
  `unresolved / ADMISSION_REJECTED`.

## Required shape and gates

- Exactly 48 cases; at least 24 answerable.
- At least 10 multilingual cases, with exact and reviewed-alias expectations represented.
- At least 8 ENERGY / TRANSPORT_WORK cases including energy, combustion, and transport.
- At least 10 hard safety negatives across boundary, subject, unit, indicator, declared
  product, source quality/admission, and forbidden escape.
- At least 5 `MORE_INPUT_NEEDED` and 5 genuine zero-recall cases.
- Geography/year applicability includes a compatible/current record outranking an
  incompatible/stale preferred-source record.
- All evidence uses public-synthetic `https://example.invalid/` locators.
- Full frozen case contract pass rate = 100%.
- Answerable Top-1 >= 90%; retrieval recall >= 95%; abstention correctness >= 90%.
- Boundary/subject/unit/forbidden escapes = 0; replay = 100%; HTTP 500 = 0.

Inputs are committed and hashed before first execution. Any runtime, evaluator,
configuration, fixture, or answer change after execution requires a new RC and new set.

Lease `CFR-RC5-SEALED-AUTHOR-005` permits only:

- `data/sealed/portfolio_rc5_cases.jsonl`
- `data/sealed/portfolio_rc5_catalog.json`
