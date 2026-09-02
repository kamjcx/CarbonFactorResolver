# CarbonFactorResolver v0.14.1 — Acceptance Closure

v0.14.1 closes the unit-system and FIN-05 acceptance work without changing any frozen
benchmark answer or formally admitting deployment factor records.

## Runtime corrections

- Conditioned `Nm3` requests remain in their stated reference state during normalization,
  allowing source-factor evidence to be applied in its declared direction.
- Every ambient/conditioned volume crossing requires explicit versioned evidence; scaled
  ambient units such as `L` cannot silently convert to or from `Nm3`.
- Otherwise-qualified candidates under an unresolved material-subtype request are exposed
  only as `REFERENCE_ONLY`. The terminal decision remains `MORE_INPUT_NEEDED` and standard
  approval cannot select them.

## Preserved evaluation history

- Sealed Unit v2: first run 31/32; unchanged post-fix regression 32/32.
- Sealed Unit v3: first run 23/24 due to an incorrect frozen expected value; NO-GO retained.
- Sealed Unit v4: independent first run 21/21, with every reported check at 100%.
- Portfolio FIN-05: correct source preserved as reference-only while subtype input remains
  required; the frozen benchmark answer is unchanged.

This remains a portfolio-ready research prototype, not a production accounting system or
formal factor catalogue. Structured electricity records without complete canonical source
evidence remain blocked.

## Verification summary

- Core package: 324 tests passed with 87.06% branch coverage on Python 3.11.
- Compatibility: 324 tests passed on both Python 3.12 and Python 3.13.
- Offline acceptance harness: 13 tests passed with 43.24% branch coverage.
- Evaluation critical path: 6 tests passed with 84.10% branch coverage.
- FactorBench v1/v2/v3, frozen unit v1, sealed unit v2 and sealed unit v4 passed.
- Ruff, mypy, source compilation, package build and 0.14.1 archive isolation passed.
- Container release eligibility is decided by the protected remote CI `container` job.
