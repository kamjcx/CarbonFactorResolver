# CarbonFactorResolver v0.14.0 — Release Notes

v0.14.0 is the stable portfolio release and is runtime-equivalent to rc.6. RC3-RC5 remain
preserved historical NO-GO evidence; no failed result or frozen answer was rewritten.

## Highlights

- Dimension-aware mass, energy, volume, transport-work and count qualification.
- Exact lifecycle-stage and factor-subject safety matrices.
- Stable fail-closed public reason codes with exception redaction.
- Human review, rejection monotonicity and immutable locking.
- FactorBench V2/V3 adjudication without rewriting historical versions.
- Frozen Unit Regression Set with honest 24/28 first-run and 28/28 post-fix reporting.
- Public-synthetic fixtures, data-license controls and release artifact inspection.

## Verification summary

Core: 315 tests, 87.05% branch coverage. Evaluator critical path: 84.10%. FactorBench V3:
57/57. RC6 sealed first run: 48/48 full case contracts, 100% Top-1, recall, abstention and
deterministic replay, with zero boundary, subject, unit, forbidden-candidate or HTTP-500
failures.

## Release assets

- wheel and source distribution;
- Docker image digest;
- sealed raw result JSON and SHA-256 manifest;
- three redacted demo traces;
- source/lock/artifact checksum list.

No ecoinvent data, customer records, private evidence or formal factor catalogue is included.
