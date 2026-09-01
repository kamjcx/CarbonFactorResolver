# CFR v0.14.0-rc.3 Sealed First Run

Status: **NO-GO**

The RC3 inputs were committed before execution at `fa96997c9c9cbc0df2c02a9319233a6c9b383502`.
The runtime/configuration freeze was `d5abf8e0c110e692e79d99d02f9e9d8de7347bb5`.
The first run was executed once on 2026-09-02. Its raw JSON is preserved unchanged at
`outputs/sealed_rc3_first_run.json` with SHA-256
`a4c4e4ba6abc49d0d1ea2a9bbca27a1c1deb2e7d634e0eac70433cddb803f929`.

## Result

- Cases: 48
- Full frozen case contracts passed: 35/48 (72.92%)
- Answerable Top-1: 100%
- Retrieval recall before gate: 100%
- Abstention correctness: 100%
- Boundary violations: 0
- Subject violations: 0
- Unit-dimension violations: 0
- Forbidden-candidate escapes: 0
- Deterministic replay: 100%
- Unhandled HTTP 500: 0

Thirteen cases did not satisfy the complete frozen expectation:

- Ten answerable cases returned `reference_review_required` instead of
  `recommendation_ready`: `R3-ALIAS-002`, `R3-ALIAS-004`, `R3-ALIAS-006`,
  `R3-ALIAS-008`, `R3-ALIAS-010`, `R3-ALIAS-012`, `R3-OPUNIT-017`,
  `R3-OPUNIT-019`, `R3-APPLY-022`, and `R3-APPLY-024`.
- Three missing-subject cases returned the expected `more_input_needed` status but also
  returned the unanticipated `ADMISSION_REJECTED` reason code: `R3-MORE-042`,
  `R3-MORE-043`, and `R3-MORE-044`.

## Gate defect discovered

The v1 evaluator checked aggregate safety thresholds but did not require every frozen case's
HTTP status, terminal status, reason codes, candidate constraints, and Trace expectation to
pass. It therefore emitted `release_gate.passed=true` despite `passed_count=35`.

That output is retained verbatim as evidence; it is not treated as a release approval. The
v2 evaluator adds an explicit 100% full-case-contract gate. RC3 is permanently NO-GO. No
RC3 runtime or answer file will be changed, and RC4 requires a wholly new sealed dataset.
