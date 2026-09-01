# CarbonFactorResolver v0.14.0 — Draft Release Notes

> Draft only. Final release is blocked by the rc.2 sealed Top-1 gate.

## Highlights

- Dimension-aware mass, energy, volume, transport-work and count qualification.
- Exact lifecycle-stage and factor-subject safety matrices.
- Stable fail-closed public reason codes with exception redaction.
- Human review, rejection monotonicity and immutable locking.
- FactorBench V2 adjudication without rewriting V1 history.
- Frozen Unit Regression Set with honest 24/28 first-run and 28/28 post-fix reporting.
- Public-synthetic fixtures, data-license controls and release artifact inspection.

## Verification summary

Core: 286 tests, 86.90% branch coverage. Evaluator critical path: 84.10%. FactorBench V2
abstention: 100%. rc.2 sealed run: Recall 100%, abstention 100%, safety escapes 0, deterministic
replay 100%, HTTP 500 0, Answerable Top-1 83.33% (**below the 90% release gate**).

## Assets planned after a future GO

- wheel and source distribution;
- Docker image digest;
- sealed raw result JSON and SHA-256 manifest;
- three redacted demo traces;
- source/lock/artifact checksum list.

No ecoinvent data, customer records, private evidence or formal factor catalogue is included.

