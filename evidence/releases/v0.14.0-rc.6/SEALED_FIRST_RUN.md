# CFR v0.14.0-rc.6 Sealed First Run

Status: **GO**

Runtime/evaluator freeze: `1c8be4ca3ef0a1402a0ef343a024972e7a0e6320`.
Input commit: `2d4cb669339908f5456643d1ebf94dcbf62b1f9a`.
Raw output: `outputs/sealed_rc6_first_run.json`; SHA-256
`b1437d68e3411f4ecccefb035804103801ead2aee45fe362c8b6745750ab0275`.

## Preserved first-run result

- Cases: 48
- Full frozen case contracts: 48/48 (100%)
- Answerable cases: 26
- Answerable Top-1: 100%
- Retrieval recall before gate: 100%
- Abstention cases: 22
- Abstention correctness: 100%
- Boundary violations: 0
- Subject violations: 0
- Unit-dimension violations: 0
- Forbidden-candidate escapes: 0
- Deterministic replay: 100%
- Unhandled HTTP 500: 0

The v2 evaluator returned `release_gate.passed=true`, including the 100% full-case-contract
gate. Inputs and results are public-synthetic. This evidence supports portfolio release of a
reproducible research prototype; it is not a real-world accuracy or production accounting
claim and does not approve any formal factor.
