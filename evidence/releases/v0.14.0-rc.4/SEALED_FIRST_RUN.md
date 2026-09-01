# CFR v0.14.0-rc.4 Sealed First Run

Status: **NO-GO**

Runtime/evaluator freeze: `b21b8ea48a4ec400372db1621c5d3313f9fe7ca8`.
Input commit: `66836c7a932de32d7768ba3f2a9eec17f1b297c6`.
The raw first-run output is preserved unchanged at `outputs/sealed_rc4_first_run.json`;
SHA-256: `6e619bcbaf26cf225e4b0ab7935906ec565cd711a1b6d4454e1dd90b3baa69ba`.

## Result

- Full case contracts: 36/48 (75.00%)
- Answerable Top-1: 100%
- Retrieval recall before gate: 100%
- Abstention correctness: 100%
- Boundary/subject/unit violations: 0/0/0
- Forbidden-candidate escapes: 0
- Deterministic replay: 100%
- Unhandled HTTP 500: 0

The corrected v2 gate returned `passed=false` as required. Nine reviewed-alias or
applicability cases correctly stayed `reference_review_required` rather than the frozen
`recommendation_ready` expectation. Three missing-subject cases returned the correct
`more_input_needed` status but also exposed `ADMISSION_REJECTED`, conflating an incomplete
request with catalogue rejection.

RC4 remains permanently NO-GO. RC5 removes the misleading admission reason when an explicit
request gap already controls the terminal state, retains aliases as review-only, and uses a
wholly new sealed dataset. No RC4 answer or result is rewritten.
