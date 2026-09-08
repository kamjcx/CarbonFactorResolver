# Portfolio audit — 2026-09-09

Baseline: `9aaee4227f300eeea01481cc50e991cacb501bb6` (v0.14.4 main).
Audited a clean clone; the original carbon-report working directory was not modified.

## Confirmed defects and fixes

- **P2 API ownership race:** public and debug resolution could interleave for one ID,
  leaving a successful stored result without its authorization owner. Debug now shares
  the scoped lock and reserves ownership before execution. Existing owners return 409.
  Same-scope and cross-scope, in both execution orders, have regression coverage.
- **P2 dashboard contract mismatch:** unavailable admin benchmark/compare routes were
  exposed as usable tabs; hidden Trace fields rendered as zero counts. The default
  dashboard now uses the public DTO only and shows input, surfaced candidates and status.
- **P2 missing decision explanation:** messages, questions and reason codes were omitted.
  They now render alongside source citations, boundary, evidence hash and limitations.
- **P2 stale result/error handling:** requests now clear previous results, disable repeat
  submission while pending and display structured API errors as readable text.
- **P2 unreproducible demo script:** replaced catalog-specific examples and private Trace
  instructions with the three bundled quickstart examples verified in the browser.

## Validation

- Windows / Python 3.14.4, frozen uv dependencies.
- Baseline: 587 tests passed, 86.96% branch coverage (85% gate).
- Post-fix original suite: 587 passed, 86.91% branch coverage; four additional concurrency tests pass.
- Ruff and mypy checked; independent read-only reviewer reproduced the race and verified
  all four repaired interleavings, including tenant isolation.
- Browser: qualified result 8400 kgCO2e/t; missing-route reference-only results; unknown
  material refusal; expanded evidence. Desktop and 390x844 mobile visually inspected.
  Mobile document width equals viewport content width; no page-level horizontal overflow.

## Remaining limits

This audit does not establish absence of every defect. Docker/image scanning and Linux CI
were not reproduced locally. Existing Python 3.14 warnings include Starlette test-client
httpx deprecation and SQLite connections left open by the portfolio evaluation harness.
No commercial/customer factor data was used, and no approval or calculation was changed.
